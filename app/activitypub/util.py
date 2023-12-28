from __future__ import annotations

import json
import os
from datetime import timedelta
from random import randint
from typing import Union, Tuple
from flask import current_app, request, g
from sqlalchemy import text
from app import db, cache, constants, celery
from app.models import User, Post, Community, BannedInstances, File, PostReply, AllowedInstances, Instance, utcnow, \
    PostVote, PostReplyVote, ActivityPubLog
import time
import base64
import requests
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from app.constants import *
from urllib.parse import urlparse
from PIL import Image, ImageOps
from io import BytesIO

from app.utils import get_request, allowlist_html, html_to_markdown, get_setting, ap_datetime, markdown_to_html, \
    is_image_url, domain_from_url, gibberish, ensure_directory_exists, markdown_to_text


def public_key():
    if not os.path.exists('./public.pem'):
        os.system('openssl genrsa -out private.pem 2048')
        os.system('openssl rsa -in private.pem -outform PEM -pubout -out public.pem')
    else:
        publicKey = open('./public.pem', 'r').read()
        PUBLICKEY = publicKey.replace('\n', '\\n')  # JSON-LD doesn't want to work with linebreaks,
        # but needs the \n character to know where to break the line ;)
        return PUBLICKEY


def community_members(community_id):
    sql = 'SELECT COUNT(id) as c FROM "user" as u '
    sql += 'INNER JOIN community_member cm on u.id = cm.user_id '
    sql += 'WHERE u.banned is false AND u.deleted is false AND cm.is_banned is false and cm.community_id = :community_id'
    return db.session.execute(text(sql), {'community_id': community_id}).scalar()


def users_total():
    return db.session.execute(text(
        'SELECT COUNT(id) as c FROM "user" WHERE ap_id is null AND verified is true AND banned is false AND deleted is false')).scalar()


def active_half_year():
    return db.session.execute(text(
        "SELECT COUNT(id) as c FROM \"user\" WHERE last_seen >= CURRENT_DATE - INTERVAL '6 months' AND ap_id is null AND verified is true AND banned is false AND deleted is false")).scalar()


def active_month():
    return db.session.execute(text(
        "SELECT COUNT(id) as c FROM \"user\" WHERE last_seen >= CURRENT_DATE - INTERVAL '1 month' AND ap_id is null AND verified is true AND banned is false AND deleted is false")).scalar()


def local_posts():
    return db.session.execute(text('SELECT COUNT(id) as c FROM "post" WHERE ap_id is null')).scalar()


def local_comments():
    return db.session.execute(text('SELECT COUNT(id) as c FROM "post_reply" WHERE ap_id is null')).scalar()


def send_activity(sender: User, host: str, content: str):
    date = time.strftime('%a, %d %b %Y %H:%M:%S UTC', time.gmtime())

    private_key = serialization.load_pem_private_key(sender.private_key, password=None)

    # todo: look up instance details to set host_inbox
    host_inbox = '/inbox'

    signed_string = f"(request-target): post {host_inbox}\nhost: {host}\ndate: " + date
    signature = private_key.sign(signed_string.encode('utf-8'), padding.PKCS1v15(), hashes.SHA256())
    encoded_signature = base64.b64encode(signature).decode('utf-8')

    # Construct the Signature header
    header = f'keyId="https://{current_app.config["SERVER_NAME"]}/u/{sender.user_name}",headers="(request-target) host date",signature="{encoded_signature}"'

    # Create headers for the request
    headers = {
        'Host': host,
        'Date': date,
        'Signature': header
    }

    # Make the HTTP request
    try:
        response = requests.post(f'https://{host}{host_inbox}', headers=headers, data=content,
                                 timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException:
        time.sleep(1)
        response = requests.post(f'https://{host}{host_inbox}', headers=headers, data=content,
                                 timeout=REQUEST_TIMEOUT / 2)
    return response.status_code


def post_to_activity(post: Post, community: Community):
    activity_data = {
        "actor": f"https://{current_app.config['SERVER_NAME']}/c/{community.name}",
        "to": [
            "https://www.w3.org/ns/activitystreams#Public"
        ],
        "object": {
            "id": f"https://{current_app.config['SERVER_NAME']}/activities/create/{post.ap_create_id}",
            "actor": f"https://{current_app.config['SERVER_NAME']}/u/{post.author.user_name}",
            "to": [
                "https://www.w3.org/ns/activitystreams#Public"
            ],
            "object": {
                "type": "Page",
                "id": f"https://{current_app.config['SERVER_NAME']}/post/{post.id}",
                "attributedTo": f"https://{current_app.config['SERVER_NAME']}/u/{post.author.user_name}",
                "to": [
                    f"https://{current_app.config['SERVER_NAME']}/c/{community.name}",
                    "https://www.w3.org/ns/activitystreams#Public"
                ],
                "name": post.title,
                "cc": [],
                "content": post.body_html,
                "summary": markdown_to_text(post.body),
                "mediaType": "text/html",
                "source": {
                    "content": post.body,
                    "mediaType": "text/markdown"
                },
                "attachment": [],
                "commentsEnabled": True,
                "sensitive": post.nsfw or post.nsfl,
                "published": ap_datetime(post.created_at),
                "audience": f"https://{current_app.config['SERVER_NAME']}/c/{community.name}"
            },
            "cc": [
                f"https://{current_app.config['SERVER_NAME']}/c/{community.name}"
            ],
            "type": "Create",
            "audience": f"https://{current_app.config['SERVER_NAME']}/c/{community.name}"
        },
        "cc": [
            f"https://{current_app.config['SERVER_NAME']}/c/{community.name}/followers"
        ],
        "type": "Announce",
        "id": f"https://{current_app.config['SERVER_NAME']}/activities/announce/{post.ap_announce_id}"
    }
    if post.edited_at is not None:
        activity_data["object"]["object"]["updated"] = post.edited_at
    if post.language is not None:
        activity_data["object"]["object"]["language"] = {"identifier": post.language}
    if post.type == POST_TYPE_LINK and post.url is not None:
        activity_data["object"]["object"]["attachment"] = {"href": post.url, "type": "Link"}
    if post.image_id is not None:
        activity_data["object"]["object"]["image"] = {"href": post.image.source_url, "type": "Image"}
    return activity_data


def banned_user_agents():
    return []  # todo: finish this function


@cache.memoize(150)
def instance_blocked(host: str) -> bool:
    host = host.lower()
    if 'https://' in host or 'http://' in host:
        host = urlparse(host).hostname
    instance = BannedInstances.query.filter_by(domain=host.strip()).first()
    return instance is not None


@cache.memoize(150)
def instance_allowed(host: str) -> bool:
    host = host.lower()
    if 'https://' in host or 'http://' in host:
        host = urlparse(host).hostname
    instance = AllowedInstances.query.filter_by(domain=host.strip()).first()
    return instance is not None


def find_actor_or_create(actor: str) -> Union[User, Community, None]:
    user = None
    # actor parameter must be formatted as https://server/u/actor or https://server/c/actor

    # Initially, check if the user exists in the local DB already
    if current_app.config['SERVER_NAME'] + '/c/' in actor:
        return Community.query.filter_by(
            ap_profile_id=actor).first()  # finds communities formatted like https://localhost/c/*

    if current_app.config['SERVER_NAME'] + '/u/' in actor:
        user = User.query.filter_by(user_name=actor.split('/')[-1], ap_id=None, banned=False).first()  # finds local users
        if user is None:
            return None
    elif actor.startswith('https://'):
        server, address = extract_domain_and_actor(actor)
        if get_setting('use_allowlist', False):
            if not instance_allowed(server):
                return None
        else:
            if instance_blocked(server):
                return None
        user = User.query.filter_by(
            ap_profile_id=actor).first()  # finds users formatted like https://kbin.social/u/tables
        if user and user.banned:
            return None
        if user is None:
            user = Community.query.filter_by(ap_profile_id=actor).first()

    if user is not None:
        if not user.is_local() and user.ap_fetched_at < utcnow() - timedelta(days=7):
            # To reduce load on remote servers, refreshing the user profile happens after a delay of 1 to 10 seconds. Meanwhile, subsequent calls to
            # find_actor_or_create() which happen to be for the same actor might queue up refreshes of the same user. To avoid this, set a flag to
            # indicate that user is currently being refreshed.
            refresh_in_progress = cache.get(f'refreshing_{user.id}')
            if not refresh_in_progress:
                cache.set(f'refreshing_{user.id}', True, timeout=300)
                refresh_user_profile(user.id)
        return user
    else:   # User does not exist in the DB, it's going to need to be created from it's remote home instance
        if actor.startswith('https://'):
            actor_data = get_request(actor, headers={'Accept': 'application/activity+json'})
            if actor_data.status_code == 200:
                actor_json = actor_data.json()
                actor_data.close()
                return actor_json_to_model(actor_json, address, server)
        else:
            # retrieve user details via webfinger, etc
            # todo: try, except block around every get_request
            webfinger_data = get_request(f"https://{server}/.well-known/webfinger",
                                         params={'resource': f"acct:{address}@{server}"})
            if webfinger_data.status_code == 200:
                webfinger_json = webfinger_data.json()
                webfinger_data.close()
                for links in webfinger_json['links']:
                    if 'rel' in links and links['rel'] == 'self':  # this contains the URL of the activitypub profile
                        type = links['type'] if 'type' in links else 'application/activity+json'
                        # retrieve the activitypub profile
                        actor_data = get_request(links['href'], headers={'Accept': type})
                        # to see the structure of the json contained in actor_data, do a GET to https://lemmy.world/c/technology with header Accept: application/activity+json
                        if actor_data.status_code == 200:
                            actor_json = actor_data.json()
                            actor_data.close()
                            return actor_json_to_model(actor_json, address, server)
    return None


def extract_domain_and_actor(url_string: str):
    # Parse the URL
    parsed_url = urlparse(url_string)

    # Extract the server domain name
    server_domain = parsed_url.netloc

    # Extract the part of the string after the last '/' character
    actor = parsed_url.path.split('/')[-1]

    return server_domain, actor


def refresh_user_profile(user_id):
    if current_app.debug:
        refresh_user_profile_task(user_id)
    else:
        refresh_user_profile_task.apply_async(args=(user_id), countdown=randint(1, 10))


@celery.task
def refresh_user_profile_task(user_id):
    user = User.query.get(user_id)
    if user:
        actor_data = get_request(user.ap_profile_id, headers={'Accept': 'application/activity+json'})
        if actor_data.status_code == 200:
            activity_json = actor_data.json()
            actor_data.close()
            user.user_name = activity_json['preferredUsername']
            user.about_html = parse_summary(activity_json)
            user.ap_fetched_at = utcnow()
            user.public_key=activity_json['publicKey']['publicKeyPem']

            avatar_changed = cover_changed = False
            if 'icon' in activity_json:
                if activity_json['icon']['url'] != user.avatar.source_url:
                    user.avatar.delete_from_disk()
                    avatar = File(source_url=activity_json['icon']['url'])
                    user.avatar = avatar
                    db.session.add(avatar)
                    avatar_changed = True
            if 'image' in activity_json:
                if activity_json['image']['url'] != user.cover.source_url:
                    user.cover.delete_from_disk()
                    cover = File(source_url=activity_json['image']['url'])
                    user.cover = cover
                    db.session.add(cover)
                    cover_changed = True
            db.session.commit()
            if user.avatar_id and avatar_changed:
                make_image_sizes(user.avatar_id, 40, 250, 'users')
            if user.cover_id and cover_changed:
                make_image_sizes(user.cover_id, 700, 1600, 'users')


def actor_json_to_model(activity_json, address, server):
    if activity_json['type'] == 'Person':
        user = User(user_name=activity_json['preferredUsername'],
                    email=f"{address}@{server}",
                    about_html=parse_summary(activity_json),
                    created=activity_json['published'] if 'published' in activity_json else utcnow(),
                    ap_id=f"{address}@{server}",
                    ap_public_url=activity_json['id'],
                    ap_profile_id=activity_json['id'],
                    ap_inbox_url=activity_json['endpoints']['sharedInbox'],
                    ap_followers_url=activity_json['followers'] if 'followers' in activity_json else None,
                    ap_preferred_username=activity_json['preferredUsername'],
                    ap_fetched_at=utcnow(),
                    ap_domain=server,
                    public_key=activity_json['publicKey']['publicKeyPem'],
                    instance_id=find_instance_id(server)
                    # language=community_json['language'][0]['identifier'] # todo: language
                    )
        if 'icon' in activity_json:
            avatar = File(source_url=activity_json['icon']['url'])
            user.avatar = avatar
            db.session.add(avatar)
        if 'image' in activity_json:
            cover = File(source_url=activity_json['image']['url'])
            user.cover = cover
            db.session.add(cover)
        db.session.add(user)
        db.session.commit()
        if user.avatar_id:
            make_image_sizes(user.avatar_id, 40, 250, 'users')
        if user.cover_id:
            make_image_sizes(user.cover_id, 700, 1600, 'users')
        return user
    elif activity_json['type'] == 'Group':
        if 'attributedTo' in activity_json:  # lemmy and mbin
            mods_url = activity_json['attributedTo']
        elif 'moderators' in activity_json:  # kbin
            mods_url = activity_json['moderators']
        else:
            mods_url = None
        community = Community(name=activity_json['preferredUsername'],
                              title=activity_json['name'],
                              description=activity_json['summary'] if 'summary' in activity_json else '',
                              rules=activity_json['rules'] if 'rules' in activity_json else '',
                              rules_html=markdown_to_html(activity_json['rules'] if 'rules' in activity_json else ''),
                              nsfw=activity_json['sensitive'],
                              restricted_to_mods=activity_json['postingRestrictedToMods'],
                              created_at=activity_json['published'] if 'published' in activity_json else utcnow(),
                              last_active=activity_json['updated'] if 'updated' in activity_json else utcnow(),
                              ap_id=f"{address[1:]}",
                              ap_public_url=activity_json['id'],
                              ap_profile_id=activity_json['id'],
                              ap_followers_url=activity_json['followers'],
                              ap_inbox_url=activity_json['endpoints']['sharedInbox'],
                              ap_moderators_url=mods_url,
                              ap_fetched_at=utcnow(),
                              ap_domain=server,
                              public_key=activity_json['publicKey']['publicKeyPem'],
                              # language=community_json['language'][0]['identifier'] # todo: language
                              instance_id=find_instance_id(server),
                              low_quality='memes' in activity_json['preferredUsername']
                              )
        # parse markdown and overwrite html field with result
        if 'source' in activity_json and \
                activity_json['source']['mediaType'] == 'text/markdown':
            community.description = activity_json['source']['content']
            community.description_html = markdown_to_html(community.description)
        elif 'content' in activity_json:
            community.description_html = allowlist_html(activity_json['content'])
            community.description = html_to_markdown(community.description_html)
        if 'icon' in activity_json:
            icon = File(source_url=activity_json['icon']['url'])
            community.icon = icon
            db.session.add(icon)
        if 'image' in activity_json:
            image = File(source_url=activity_json['image']['url'])
            community.image = image
            db.session.add(image)
        db.session.add(community)
        db.session.commit()
        if community.icon_id:
            make_image_sizes(community.icon_id, 60, 250, 'communities')
        if community.image_id:
            make_image_sizes(community.image_id, 700, 1600, 'communities')
        return community


def post_json_to_model(post_json, user, community) -> Post:
    post = Post(user_id=user.id, community_id=community.id,
                title=post_json['name'],
                comments_enabled=post_json['commentsEnabled'],
                sticky=post_json['stickied'] if 'stickied' in post_json else False,
                nsfw=post_json['sensitive'],
                nsfl=post_json['nsfl'] if 'nsfl' in post_json else False,
                ap_id=post_json['id'],
                type=constants.POST_TYPE_ARTICLE,
                posted_at=post_json['published'],
                last_active=post_json['published'],
                instance_id=user.instance_id
                )
    if 'source' in post_json and \
            post_json['source']['mediaType'] == 'text/markdown':
        post.body = post_json['source']['content']
        post.body_html = markdown_to_html(post.body)
    elif 'content' in post_json:
        post.body_html = allowlist_html(post_json['content'])
        post.body = html_to_markdown(post.body_html)
    if 'attachment' in post_json and \
            len(post_json['attachment']) > 0 and \
            'type' in post_json['attachment'][0]:
        if post_json['attachment'][0]['type'] == 'Link':
            post.url = post_json['attachment'][0]['href']
            if is_image_url(post.url):
                post.type = POST_TYPE_IMAGE
            else:
                post.type = POST_TYPE_LINK
            domain = domain_from_url(post.url)
            if not domain.banned:
                post.domain_id = domain.id
            else:
                post = None
    if 'image' in post_json:
        image = File(source_url=post_json['image']['url'])
        db.session.add(image)
        post.image = image

    if post is not None:
        db.session.add(post)
        community.post_count += 1
        db.session.commit()
    return post


# Save two different versions of a File, after downloading it from file.source_url. Set a width parameter to None to avoid generating one of that size
def make_image_sizes(file_id, thumbnail_width=50, medium_width=120, directory='posts'):
    if current_app.debug:
        make_image_sizes_async(file_id, thumbnail_width, medium_width, directory)
    else:
        make_image_sizes_async.apply_async(args=(file_id, thumbnail_width, medium_width, directory), countdown=randint(1, 10))  # Delay by up to 10 seconds so servers do not experience a stampede of requests all in the same second


@celery.task
def make_image_sizes_async(file_id, thumbnail_width, medium_width, directory):
    file = File.query.get(file_id)
    if file and file.source_url:
        try:
            source_image_response = get_request(file.source_url)
        except:
            pass
        else:
            if source_image_response.status_code == 200:
                content_type = source_image_response.headers.get('content-type')
                if content_type and content_type.startswith('image'):
                    source_image = source_image_response.content
                    source_image_response.close()

                    file_ext = os.path.splitext(file.source_url)[1]

                    new_filename = gibberish(15)

                    # set up the storage directory
                    directory = f'app/static/media/{directory}/' + new_filename[0:2] + '/' + new_filename[2:4]
                    ensure_directory_exists(directory)

                    # file path and names to store the resized images on disk
                    final_place = os.path.join(directory, new_filename + file_ext)
                    final_place_thumbnail = os.path.join(directory, new_filename + '_thumbnail.webp')

                    # Load image data into Pillow
                    image = Image.open(BytesIO(source_image))
                    image = ImageOps.exif_transpose(image)
                    img_width = image.width
                    img_height = image.height

                    # Resize the image to medium
                    if medium_width:
                        if img_width > medium_width:
                            image.thumbnail((medium_width, medium_width))
                        image.save(final_place)
                        file.file_path = final_place
                        file.width = image.width
                        file.height = image.height

                    # Resize the image to a thumbnail (webp)
                    if thumbnail_width:
                        if img_width > thumbnail_width:
                            image.thumbnail((thumbnail_width, thumbnail_width))
                        image.save(final_place_thumbnail, format="WebP", quality=93)
                        file.thumbnail_path = final_place_thumbnail
                        file.thumbnail_width = image.width
                        file.thumbnail_height = image.height

                    db.session.commit()




# create a summary from markdown if present, otherwise use html if available
def parse_summary(user_json) -> str:
    if 'source' in user_json and user_json['source'].get('mediaType') == 'text/markdown':
        # Convert Markdown to HTML
        markdown_text = user_json['source']['content']
        html_content = html_to_markdown(markdown_text)
        return html_content
    elif 'summary' in user_json:
        return allowlist_html(user_json['summary'])
    else:
        return ''


def default_context():
    context = [
        "https://www.w3.org/ns/activitystreams",
        "https://w3id.org/security/v1",
    ]
    if current_app.config['FULL_AP_CONTEXT']:
        context.append({
            "lemmy": "https://join-lemmy.org/ns#",
            "litepub": "http://litepub.social/ns#",
            "pt": "https://joinpeertube.org/ns#",
            "sc": "http://schema.org/",
            "ChatMessage": "litepub:ChatMessage",
            "commentsEnabled": "pt:commentsEnabled",
            "sensitive": "as:sensitive",
            "matrixUserId": "lemmy:matrixUserId",
            "postingRestrictedToMods": "lemmy:postingRestrictedToMods",
            "removeData": "lemmy:removeData",
            "stickied": "lemmy:stickied",
            "moderators": {
                "@type": "@id",
                "@id": "lemmy:moderators"
            },
            "expires": "as:endTime",
            "distinguished": "lemmy:distinguished",
            "language": "sc:inLanguage",
            "identifier": "sc:identifier"
        })
    return context


def find_reply_parent(in_reply_to: str) -> Tuple[int, int, int]:
    if 'comment' in in_reply_to:
        parent_comment = PostReply.get_by_ap_id(in_reply_to)
        if not parent_comment:
            return (None, None, None)
        parent_comment_id = parent_comment.id
        post_id = parent_comment.post_id
        root_id = parent_comment.root_id
    elif 'post' in in_reply_to:
        parent_comment_id = None
        post = Post.get_by_ap_id(in_reply_to)
        if not post:
            return (None, None, None)
        post_id = post.id
        root_id = None
    else:
        parent_comment_id = None
        root_id = None
        post_id = None
        post = Post.get_by_ap_id(in_reply_to)
        if post:
            post_id = post.id
        else:
            parent_comment = PostReply.get_by_ap_id(in_reply_to)
            if parent_comment:
                parent_comment_id = parent_comment.id
                post_id = parent_comment.post_id
                root_id = parent_comment.root_id
            else:
                return (None, None, None)

    return post_id, parent_comment_id, root_id


def find_liked_object(ap_id) -> Union[Post, PostReply, None]:
    post = Post.get_by_ap_id(ap_id)
    if post:
        return post
    else:
        post_reply = PostReply.get_by_ap_id(ap_id)
        if post_reply:
            return post_reply
    return None


def find_instance_id(server):
    server = server.strip()
    instance = Instance.query.filter_by(domain=server).first()
    if instance:
        return instance.id
    else:
        # Our instance does not know about {server} yet. Initially, create a sparse row in the 'instance' table and spawn a background
        # task to update the row with more details later
        new_instance = Instance(domain=server, software='unknown', created_at=utcnow())
        db.session.add(new_instance)
        db.session.commit()

        # Spawn background task
        refresh_instance_profile(new_instance.id)

        return new_instance.id


def refresh_instance_profile(instance_id: int):
    if current_app.debug:
        refresh_instance_profile_task(instance_id)
    else:
        refresh_instance_profile_task.apply_async(args=(instance_id), countdown=randint(1, 10))


@celery.task
def refresh_instance_profile_task(instance_id: int):
    instance = Instance.query.get(instance_id)
    try:
        instance_data = get_request(f"https://{instance.domain}", headers={'Accept': 'application/activity+json'})
    except:
        return
    if instance_data.status_code == 200:
        try:
            instance_json = instance_data.json()
            instance_data.close()
        except requests.exceptions.JSONDecodeError as ex:
            instance_json = {}
        if 'type' in instance_json and instance_json['type'] == 'Application':
            if instance_json['name'].lower() == 'kbin':
                software = 'Kbin'
            elif instance_json['name'].lower() == 'mbin':
                software = 'Mbin'
            else:
                software = 'Lemmy'
            instance.inbox = instance_json['inbox']
            instance.outbox = instance_json['outbox']
            instance.software = software
        else:   # it's pretty much always /inbox so just assume that it is for whatever this instance is running (mostly likely Mastodon)
            instance.inbox = f"https://{instance.domain}/inbox"
        instance.updated_at = utcnow()
        db.session.commit()


# alter the effect of upvotes based on their instance. Default to 1.0
@cache.memoize(timeout=50)
def instance_weight(domain):
    if domain:
        instance = Instance.query.filter_by(domain=domain).first()
        if instance:
            return instance.vote_weight
    return 1.0


def is_activitypub_request():
    return 'application/ld+json' in request.headers.get('Accept', '') or 'application/activity+json' in request.headers.get('Accept', '')


def activity_already_ingested(ap_id):
    return db.session.execute(text('SELECT id FROM "activity_pub_log" WHERE activity_id = :activity_id'),
                              {'activity_id': ap_id}).scalar()


def downvote_post(post, user):
    user.last_seen = utcnow()
    user.recalculate_attitude()
    existing_vote = PostVote.query.filter_by(user_id=user.id, post_id=post.id).first()
    if not existing_vote:
        effect = -1.0
        post.down_votes += 1
        post.score -= 1.0
        vote = PostVote(user_id=user.id, post_id=post.id, author_id=post.author.id,
                        effect=effect)
        post.author.reputation += effect
        db.session.add(vote)
    else:
        # remove previously cast upvote
        if existing_vote.effect > 0:
            post.author.reputation -= existing_vote.effect
            post.up_votes -= 1
            post.score -= existing_vote.effect
            db.session.delete(existing_vote)

            # apply down vote
            effect = -1.0
            post.down_votes += 1
            post.score -= 1.0
            vote = PostVote(user_id=user.id, post_id=post.id, author_id=post.author.id,
                            effect=effect)
            post.author.reputation += effect
            db.session.add(vote)
        else:
            pass  # they have already downvoted this post


def downvote_post_reply(comment, user):
    user.last_seen = utcnow()
    user.recalculate_attitude()
    existing_vote = PostReplyVote.query.filter_by(user_id=user.id,
                                                  post_reply_id=comment.id).first()
    if not existing_vote:
        effect = -1.0
        comment.down_votes += 1
        comment.score -= 1.0
        vote = PostReplyVote(user_id=user.id, post_reply_id=comment.id,
                             author_id=comment.author.id, effect=effect)
        comment.author.reputation += effect
        db.session.add(vote)
    else:
        # remove previously cast upvote
        if existing_vote.effect > 0:
            comment.author.reputation -= existing_vote.effect
            comment.up_votes -= 1
            comment.score -= existing_vote.effect
            db.session.delete(existing_vote)

            # apply down vote
            effect = -1.0
            comment.down_votes += 1
            comment.score -= 1.0
            vote = PostReplyVote(user_id=user.id, post_reply_id=comment.id,
                                 author_id=comment.author.id, effect=effect)
            comment.author.reputation += effect
            db.session.add(vote)
        else:
            pass  # they have already downvoted this reply


def upvote_post_reply(comment, user):
    user.last_seen = utcnow()
    user.recalculate_attitude()
    effect = instance_weight(user.ap_domain)
    existing_vote = PostReplyVote.query.filter_by(user_id=user.id,
                                                  post_reply_id=comment.id).first()
    if not existing_vote:
        comment.up_votes += 1
        comment.score += effect
        vote = PostReplyVote(user_id=user.id, post_reply_id=comment.id,
                             author_id=comment.author.id, effect=effect)
        if comment.community.low_quality and effect > 0:
            effect = 0
        comment.author.reputation += effect
        db.session.add(vote)
    else:
        # remove previously cast downvote
        if existing_vote.effect < 0:
            comment.author.reputation -= existing_vote.effect
            comment.down_votes -= 1
            comment.score -= existing_vote.effect
            db.session.delete(existing_vote)

            # apply up vote
            comment.up_votes += 1
            comment.score += effect
            vote = PostReplyVote(user_id=user.id, post_reply_id=comment.id,
                                 author_id=comment.author.id, effect=effect)
            if comment.community.low_quality and effect > 0:
                effect = 0
            comment.author.reputation += effect
            db.session.add(vote)
        else:
            pass  # they have already upvoted this reply


def upvote_post(post, user):
    user.last_seen = utcnow()
    user.recalculate_attitude()
    effect = instance_weight(user.ap_domain)
    existing_vote = PostVote.query.filter_by(user_id=user.id, post_id=post.id).first()
    if not existing_vote:
        post.up_votes += 1
        post.score += effect
        vote = PostVote(user_id=user.id, post_id=post.id, author_id=post.author.id,
                        effect=effect)
        if post.community.low_quality and effect > 0:
            effect = 0
        post.author.reputation += effect
        db.session.add(vote)
    else:
        # remove previous cast downvote
        if existing_vote.effect < 0:
            post.author.reputation -= existing_vote.effect
            post.down_votes -= 1
            post.score -= existing_vote.effect
            db.session.delete(existing_vote)

            # apply up vote
            post.up_votes += 1
            post.score += effect
            vote = PostVote(user_id=user.id, post_id=post.id, author_id=post.author.id,
                            effect=effect)
            if post.community.low_quality and effect > 0:
                effect = 0
            post.author.reputation += effect
            db.session.add(vote)


def delete_post_or_comment(user_ap_id, community_ap_id, to_be_deleted_ap_id):
    if current_app.debug:
        delete_post_or_comment_task(user_ap_id, community_ap_id, to_be_deleted_ap_id)
    else:
        delete_post_or_comment_task.delay(user_ap_id, community_ap_id, to_be_deleted_ap_id)


@celery.task
def delete_post_or_comment_task(user_ap_id, community_ap_id, to_be_deleted_ap_id):
    deletor = find_actor_or_create(user_ap_id)
    community = find_actor_or_create(community_ap_id)
    to_delete = find_liked_object(to_be_deleted_ap_id)

    if deletor and community and to_delete:
        if deletor.is_admin() or community.is_moderator(deletor) or to_delete.author.id == deletor.id:
            if isinstance(to_delete, Post):
                to_delete.delete_dependencies()
                to_delete.flush_cache()
                db.session.delete(to_delete)
                db.session.commit()
            elif isinstance(to_delete, PostReply):
                to_delete.post.flush_cache()
                if to_delete.has_replies():
                    to_delete.body = 'Deleted by author' if to_delete.author.id == deletor.id else 'Deleted by moderator'
                    to_delete.body_html = markdown_to_html(to_delete.body)
                else:
                    to_delete.delete_dependencies()
                    db.session.delete(to_delete)
                db.session.commit()


def lemmy_site_data():
    site = g.site
    data = {
      "site_view": {
        "site": {
          "id": 1,
          "name": site.name,
          "sidebar": site.sidebar,
          "published": site.created_at.isoformat(),
          "updated": site.updated.isoformat(),
          "icon": "https://lemmy.nz/pictrs/image/d308ef8d-4381-4a7a-b047-569ed5b8dd88.png",
          "banner": "https://lemmy.nz/pictrs/image/68beebd5-4e01-44b6-bd4e-008b0d443ac1.png",
          "description": site.description,
          "actor_id": f"https://{current_app.config['SERVER_NAME']}/",
          "last_refreshed_at": site.updated.isoformat(),
          "inbox_url": f"https://{current_app.config['SERVER_NAME']}/inbox",
          "public_key": site.public_key,
          "instance_id": 1
        },
        "local_site": {
          "id": 1,
          "site_id": 1,
          "site_setup": True,
          "enable_downvotes": site.enable_downvotes,
          "enable_nsfw": site.enable_nsfw,
          "enable_nsfl": site.enable_nsfl,
          "community_creation_admin_only": site.community_creation_admin_only,
          "require_email_verification": True,
          "application_question": site.application_question,
          "private_instance": False,
          "default_theme": "browser",
          "default_post_listing_type": "All",
          "hide_modlog_mod_names": True,
          "application_email_admins": True,
          "actor_name_max_length": 20,
          "federation_enabled": True,
          "captcha_enabled": True,
          "captcha_difficulty": "medium",
          "published": site.created_at.isoformat(),
          "updated": site.updated.isoformat(),
          "registration_mode": site.registration_mode,
          "reports_email_admins": site.reports_email_admins
        },
        "local_site_rate_limit": {
          "id": 1,
          "local_site_id": 1,
          "message": 999,
          "message_per_second": 60,
          "post": 50,
          "post_per_second": 600,
          "register": 20,
          "register_per_second": 3600,
          "image": 100,
          "image_per_second": 3600,
          "comment": 100,
          "comment_per_second": 600,
          "search": 999,
          "search_per_second": 600,
          "published": site.created_at.isoformat(),
        },
        "counts": {
          "id": 1,
          "site_id": 1,
          "users": 816,
          "posts": 3017,
          "comments": 19693,
          "communities": 7,
          "users_active_day": 21,
          "users_active_week": 49,
          "users_active_month": 85,
          "users_active_half_year": 312
        }
      },
      "admins": [
        {
          "person": {
            "id": 2,
            "name": "Dave",
            "avatar": "https://lemmy.nz/pictrs/image/5eb39c6b-a1f0-4cba-9832-40a5d8ffb76a.png",
            "banned": False,
            "published": "2023-06-02T09:46:20.302035",
            "actor_id": "https://lemmy.nz/u/Dave",
            "local": True,
            "deleted": False,
            "matrix_user_id": "@bechorin:matrix.org",
            "admin": True,
            "bot_account": False,
            "instance_id": 1
          },
          "counts": {
            "id": 1,
            "person_id": 2,
            "post_count": 165,
            "post_score": 1442,
            "comment_count": 2624,
            "comment_score": 10207
          }
        },
        {
          "person": {
            "id": 15059,
            "name": "idanoo",
            "banned": False,
            "published": "2023-06-08T22:13:43.366681",
            "actor_id": "https://lemmy.nz/u/idanoo",
            "local": True,
            "deleted": False,
            "matrix_user_id": "@idanoo:mtrx.nz",
            "admin": True,
            "bot_account": False,
            "instance_id": 1
          },
          "counts": {
            "id": 6544,
            "person_id": 15059,
            "post_count": 0,
            "post_score": 0,
            "comment_count": 5,
            "comment_score": 10
          }
        }
      ],
      "version": "1.0.0",
      "all_languages": [
        {
          "id": 0,
          "code": "und",
          "name": "Undetermined"
        },
        {
          "id": 1,
          "code": "aa",
          "name": "Afaraf"
        },
        {
          "id": 2,
          "code": "ab",
          "name": "аҧсуа бызшәа"
        },
        {
          "id": 3,
          "code": "ae",
          "name": "avesta"
        },
        {
          "id": 4,
          "code": "af",
          "name": "Afrikaans"
        },
        {
          "id": 5,
          "code": "ak",
          "name": "Akan"
        },
        {
          "id": 6,
          "code": "am",
          "name": "አማርኛ"
        },
        {
          "id": 7,
          "code": "an",
          "name": "aragonés"
        },
        {
          "id": 8,
          "code": "ar",
          "name": "اَلْعَرَبِيَّةُ"
        },
        {
          "id": 9,
          "code": "as",
          "name": "অসমীয়া"
        },
        {
          "id": 10,
          "code": "av",
          "name": "авар мацӀ"
        },
        {
          "id": 11,
          "code": "ay",
          "name": "aymar aru"
        },
        {
          "id": 12,
          "code": "az",
          "name": "azərbaycan dili"
        },
        {
          "id": 13,
          "code": "ba",
          "name": "башҡорт теле"
        },
        {
          "id": 14,
          "code": "be",
          "name": "беларуская мова"
        },
        {
          "id": 15,
          "code": "bg",
          "name": "български език"
        },
        {
          "id": 16,
          "code": "bi",
          "name": "Bislama"
        },
        {
          "id": 17,
          "code": "bm",
          "name": "bamanankan"
        },
        {
          "id": 18,
          "code": "bn",
          "name": "বাংলা"
        },
        {
          "id": 19,
          "code": "bo",
          "name": "བོད་ཡིག"
        },
        {
          "id": 20,
          "code": "br",
          "name": "brezhoneg"
        },
        {
          "id": 21,
          "code": "bs",
          "name": "bosanski jezik"
        },
        {
          "id": 22,
          "code": "ca",
          "name": "Català"
        },
        {
          "id": 23,
          "code": "ce",
          "name": "нохчийн мотт"
        },
        {
          "id": 24,
          "code": "ch",
          "name": "Chamoru"
        },
        {
          "id": 25,
          "code": "co",
          "name": "corsu"
        },
        {
          "id": 26,
          "code": "cr",
          "name": "ᓀᐦᐃᔭᐍᐏᐣ"
        },
        {
          "id": 27,
          "code": "cs",
          "name": "čeština"
        },
        {
          "id": 28,
          "code": "cu",
          "name": "ѩзыкъ словѣньскъ"
        },
        {
          "id": 29,
          "code": "cv",
          "name": "чӑваш чӗлхи"
        },
        {
          "id": 30,
          "code": "cy",
          "name": "Cymraeg"
        },
        {
          "id": 31,
          "code": "da",
          "name": "dansk"
        },
        {
          "id": 32,
          "code": "de",
          "name": "Deutsch"
        },
        {
          "id": 33,
          "code": "dv",
          "name": "ދިވެހި"
        },
        {
          "id": 34,
          "code": "dz",
          "name": "རྫོང་ཁ"
        },
        {
          "id": 35,
          "code": "ee",
          "name": "Eʋegbe"
        },
        {
          "id": 36,
          "code": "el",
          "name": "Ελληνικά"
        },
        {
          "id": 37,
          "code": "en",
          "name": "English"
        },
        {
          "id": 38,
          "code": "eo",
          "name": "Esperanto"
        },
        {
          "id": 39,
          "code": "es",
          "name": "Español"
        },
        {
          "id": 40,
          "code": "et",
          "name": "eesti"
        },
        {
          "id": 41,
          "code": "eu",
          "name": "euskara"
        },
        {
          "id": 42,
          "code": "fa",
          "name": "فارسی"
        },
        {
          "id": 43,
          "code": "ff",
          "name": "Fulfulde"
        },
        {
          "id": 44,
          "code": "fi",
          "name": "suomi"
        },
        {
          "id": 45,
          "code": "fj",
          "name": "vosa Vakaviti"
        },
        {
          "id": 46,
          "code": "fo",
          "name": "føroyskt"
        },
        {
          "id": 47,
          "code": "fr",
          "name": "Français"
        },
        {
          "id": 48,
          "code": "fy",
          "name": "Frysk"
        },
        {
          "id": 49,
          "code": "ga",
          "name": "Gaeilge"
        },
        {
          "id": 50,
          "code": "gd",
          "name": "Gàidhlig"
        },
        {
          "id": 51,
          "code": "gl",
          "name": "galego"
        },
        {
          "id": 52,
          "code": "gn",
          "name": "Avañe'ẽ"
        },
        {
          "id": 53,
          "code": "gu",
          "name": "ગુજરાતી"
        },
        {
          "id": 54,
          "code": "gv",
          "name": "Gaelg"
        },
        {
          "id": 55,
          "code": "ha",
          "name": "هَوُسَ"
        },
        {
          "id": 56,
          "code": "he",
          "name": "עברית"
        },
        {
          "id": 57,
          "code": "hi",
          "name": "हिन्दी"
        },
        {
          "id": 58,
          "code": "ho",
          "name": "Hiri Motu"
        },
        {
          "id": 59,
          "code": "hr",
          "name": "Hrvatski"
        },
        {
          "id": 60,
          "code": "ht",
          "name": "Kreyòl ayisyen"
        },
        {
          "id": 61,
          "code": "hu",
          "name": "magyar"
        },
        {
          "id": 62,
          "code": "hy",
          "name": "Հայերեն"
        },
        {
          "id": 63,
          "code": "hz",
          "name": "Otjiherero"
        },
        {
          "id": 64,
          "code": "ia",
          "name": "Interlingua"
        },
        {
          "id": 65,
          "code": "id",
          "name": "Bahasa Indonesia"
        },
        {
          "id": 66,
          "code": "ie",
          "name": "Interlingue"
        },
        {
          "id": 67,
          "code": "ig",
          "name": "Asụsụ Igbo"
        },
        {
          "id": 68,
          "code": "ii",
          "name": "ꆈꌠ꒿ Nuosuhxop"
        },
        {
          "id": 69,
          "code": "ik",
          "name": "Iñupiaq"
        },
        {
          "id": 70,
          "code": "io",
          "name": "Ido"
        },
        {
          "id": 71,
          "code": "is",
          "name": "Íslenska"
        },
        {
          "id": 72,
          "code": "it",
          "name": "Italiano"
        },
        {
          "id": 73,
          "code": "iu",
          "name": "ᐃᓄᒃᑎᑐᑦ"
        },
        {
          "id": 74,
          "code": "ja",
          "name": "日本語"
        },
        {
          "id": 75,
          "code": "jv",
          "name": "basa Jawa"
        },
        {
          "id": 76,
          "code": "ka",
          "name": "ქართული"
        },
        {
          "id": 77,
          "code": "kg",
          "name": "Kikongo"
        },
        {
          "id": 78,
          "code": "ki",
          "name": "Gĩkũyũ"
        },
        {
          "id": 79,
          "code": "kj",
          "name": "Kuanyama"
        },
        {
          "id": 80,
          "code": "kk",
          "name": "қазақ тілі"
        },
        {
          "id": 81,
          "code": "kl",
          "name": "kalaallisut"
        },
        {
          "id": 82,
          "code": "km",
          "name": "ខេមរភាសា"
        },
        {
          "id": 83,
          "code": "kn",
          "name": "ಕನ್ನಡ"
        },
        {
          "id": 84,
          "code": "ko",
          "name": "한국어"
        },
        {
          "id": 85,
          "code": "kr",
          "name": "Kanuri"
        },
        {
          "id": 86,
          "code": "ks",
          "name": "कश्मीरी"
        },
        {
          "id": 87,
          "code": "ku",
          "name": "Kurdî"
        },
        {
          "id": 88,
          "code": "kv",
          "name": "коми кыв"
        },
        {
          "id": 89,
          "code": "kw",
          "name": "Kernewek"
        },
        {
          "id": 90,
          "code": "ky",
          "name": "Кыргызча"
        },
        {
          "id": 91,
          "code": "la",
          "name": "latine"
        },
        {
          "id": 92,
          "code": "lb",
          "name": "Lëtzebuergesch"
        },
        {
          "id": 93,
          "code": "lg",
          "name": "Luganda"
        },
        {
          "id": 94,
          "code": "li",
          "name": "Limburgs"
        },
        {
          "id": 95,
          "code": "ln",
          "name": "Lingála"
        },
        {
          "id": 96,
          "code": "lo",
          "name": "ພາສາລາວ"
        },
        {
          "id": 97,
          "code": "lt",
          "name": "lietuvių kalba"
        },
        {
          "id": 98,
          "code": "lu",
          "name": "Kiluba"
        },
        {
          "id": 99,
          "code": "lv",
          "name": "latviešu valoda"
        },
        {
          "id": 100,
          "code": "mg",
          "name": "fiteny malagasy"
        },
        {
          "id": 101,
          "code": "mh",
          "name": "Kajin M̧ajeļ"
        },
        {
          "id": 102,
          "code": "mi",
          "name": "te reo Māori"
        },
        {
          "id": 103,
          "code": "mk",
          "name": "македонски јазик"
        },
        {
          "id": 104,
          "code": "ml",
          "name": "മലയാളം"
        },
        {
          "id": 105,
          "code": "mn",
          "name": "Монгол хэл"
        },
        {
          "id": 106,
          "code": "mr",
          "name": "मराठी"
        },
        {
          "id": 107,
          "code": "ms",
          "name": "Bahasa Melayu"
        },
        {
          "id": 108,
          "code": "mt",
          "name": "Malti"
        },
        {
          "id": 109,
          "code": "my",
          "name": "ဗမာစာ"
        },
        {
          "id": 110,
          "code": "na",
          "name": "Dorerin Naoero"
        },
        {
          "id": 111,
          "code": "nb",
          "name": "Norsk bokmål"
        },
        {
          "id": 112,
          "code": "nd",
          "name": "isiNdebele"
        },
        {
          "id": 113,
          "code": "ne",
          "name": "नेपाली"
        },
        {
          "id": 114,
          "code": "ng",
          "name": "Owambo"
        },
        {
          "id": 115,
          "code": "nl",
          "name": "Nederlands"
        },
        {
          "id": 116,
          "code": "nn",
          "name": "Norsk nynorsk"
        },
        {
          "id": 117,
          "code": "no",
          "name": "Norsk"
        },
        {
          "id": 118,
          "code": "nr",
          "name": "isiNdebele"
        },
        {
          "id": 119,
          "code": "nv",
          "name": "Diné bizaad"
        },
        {
          "id": 120,
          "code": "ny",
          "name": "chiCheŵa"
        },
        {
          "id": 121,
          "code": "oc",
          "name": "occitan"
        },
        {
          "id": 122,
          "code": "oj",
          "name": "ᐊᓂᔑᓈᐯᒧᐎᓐ"
        },
        {
          "id": 123,
          "code": "om",
          "name": "Afaan Oromoo"
        },
        {
          "id": 124,
          "code": "or",
          "name": "ଓଡ଼ିଆ"
        },
        {
          "id": 125,
          "code": "os",
          "name": "ирон æвзаг"
        },
        {
          "id": 126,
          "code": "pa",
          "name": "ਪੰਜਾਬੀ"
        },
        {
          "id": 127,
          "code": "pi",
          "name": "पाऴि"
        },
        {
          "id": 128,
          "code": "pl",
          "name": "Polski"
        },
        {
          "id": 129,
          "code": "ps",
          "name": "پښتو"
        },
        {
          "id": 130,
          "code": "pt",
          "name": "Português"
        },
        {
          "id": 131,
          "code": "qu",
          "name": "Runa Simi"
        },
        {
          "id": 132,
          "code": "rm",
          "name": "rumantsch grischun"
        },
        {
          "id": 133,
          "code": "rn",
          "name": "Ikirundi"
        },
        {
          "id": 134,
          "code": "ro",
          "name": "Română"
        },
        {
          "id": 135,
          "code": "ru",
          "name": "Русский"
        },
        {
          "id": 136,
          "code": "rw",
          "name": "Ikinyarwanda"
        },
        {
          "id": 137,
          "code": "sa",
          "name": "संस्कृतम्"
        },
        {
          "id": 138,
          "code": "sc",
          "name": "sardu"
        },
        {
          "id": 139,
          "code": "sd",
          "name": "सिन्धी"
        },
        {
          "id": 140,
          "code": "se",
          "name": "Davvisámegiella"
        },
        {
          "id": 141,
          "code": "sg",
          "name": "yângâ tî sängö"
        },
        {
          "id": 142,
          "code": "si",
          "name": "සිංහල"
        },
        {
          "id": 143,
          "code": "sk",
          "name": "slovenčina"
        },
        {
          "id": 144,
          "code": "sl",
          "name": "slovenščina"
        },
        {
          "id": 145,
          "code": "sm",
          "name": "gagana fa'a Samoa"
        },
        {
          "id": 146,
          "code": "sn",
          "name": "chiShona"
        },
        {
          "id": 147,
          "code": "so",
          "name": "Soomaaliga"
        },
        {
          "id": 148,
          "code": "sq",
          "name": "Shqip"
        },
        {
          "id": 149,
          "code": "sr",
          "name": "српски језик"
        },
        {
          "id": 150,
          "code": "ss",
          "name": "SiSwati"
        },
        {
          "id": 151,
          "code": "st",
          "name": "Sesotho"
        },
        {
          "id": 152,
          "code": "su",
          "name": "Basa Sunda"
        },
        {
          "id": 153,
          "code": "sv",
          "name": "Svenska"
        },
        {
          "id": 154,
          "code": "sw",
          "name": "Kiswahili"
        },
        {
          "id": 155,
          "code": "ta",
          "name": "தமிழ்"
        },
        {
          "id": 156,
          "code": "te",
          "name": "తెలుగు"
        },
        {
          "id": 157,
          "code": "tg",
          "name": "тоҷикӣ"
        },
        {
          "id": 158,
          "code": "th",
          "name": "ไทย"
        },
        {
          "id": 159,
          "code": "ti",
          "name": "ትግርኛ"
        },
        {
          "id": 160,
          "code": "tk",
          "name": "Türkmençe"
        },
        {
          "id": 161,
          "code": "tl",
          "name": "Wikang Tagalog"
        },
        {
          "id": 162,
          "code": "tn",
          "name": "Setswana"
        },
        {
          "id": 163,
          "code": "to",
          "name": "faka Tonga"
        },
        {
          "id": 164,
          "code": "tr",
          "name": "Türkçe"
        },
        {
          "id": 165,
          "code": "ts",
          "name": "Xitsonga"
        },
        {
          "id": 166,
          "code": "tt",
          "name": "татар теле"
        },
        {
          "id": 167,
          "code": "tw",
          "name": "Twi"
        },
        {
          "id": 168,
          "code": "ty",
          "name": "Reo Tahiti"
        },
        {
          "id": 169,
          "code": "ug",
          "name": "ئۇيغۇرچە‎"
        },
        {
          "id": 170,
          "code": "uk",
          "name": "Українська"
        },
        {
          "id": 171,
          "code": "ur",
          "name": "اردو"
        },
        {
          "id": 172,
          "code": "uz",
          "name": "Ўзбек"
        },
        {
          "id": 173,
          "code": "ve",
          "name": "Tshivenḓa"
        },
        {
          "id": 174,
          "code": "vi",
          "name": "Tiếng Việt"
        },
        {
          "id": 175,
          "code": "vo",
          "name": "Volapük"
        },
        {
          "id": 176,
          "code": "wa",
          "name": "walon"
        },
        {
          "id": 177,
          "code": "wo",
          "name": "Wollof"
        },
        {
          "id": 178,
          "code": "xh",
          "name": "isiXhosa"
        },
        {
          "id": 179,
          "code": "yi",
          "name": "ייִדיש"
        },
        {
          "id": 180,
          "code": "yo",
          "name": "Yorùbá"
        },
        {
          "id": 181,
          "code": "za",
          "name": "Saɯ cueŋƅ"
        },
        {
          "id": 182,
          "code": "zh",
          "name": "中文"
        },
        {
          "id": 183,
          "code": "zu",
          "name": "isiZulu"
        }
      ],
      "discussion_languages": [
        0,
        37
      ],
      "taglines": [
        {
          "id": 19,
          "local_site_id": 1,
          "content": "Welcome to Lemmy NZ! [Don't be a dick](https://lemmy.nz/post/63098) ~ [FAQ](https://lemmy.nz/post/31318) ~ [NZ Community List ](https://lemmy.nz/post/63156) ~ [Join Matrix chatroom](https://lemmy.nz/post/169187)\n\n",
          "published": "2023-06-28T09:53:58.605042"
        }
      ],
      "custom_emojis": []
    }
    return data
