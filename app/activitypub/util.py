import json
import os
from datetime import datetime
from typing import Union, Tuple
import markdown2
from flask import current_app
from sqlalchemy import text
from app import db, cache
from app.models import User, Post, Community, BannedInstances, File, PostReply
import time
import base64
import requests
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from app.constants import *
from urllib.parse import urlparse

from app.utils import get_request, allowlist_html


def public_key():
    if not os.path.exists('./public.pem'):
        os.system('openssl genrsa -out private.pem 2048')
        os.system('openssl rsa -in private.pem -outform PEM -pubout -out public.pem')
    else:
        publicKey = open('./public.pem', 'r').read()
        PUBLICKEY = publicKey.replace('\n', '\\n')  # JSON-LD doesn't want to work with linebreaks,
        # but needs the \n character to know where to break the line ;)
        return PUBLICKEY


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
                "mediaType": "text/html",
                "source": {
                    "content": post.body,
                    "mediaType": "text/markdown"
                },
                "attachment": [],
                "commentsEnabled": True,
                "sensitive": post.nsfw or post.nsfl,
                "published": post.created_at,
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


def validate_headers(headers, body):
    if headers['content-type'] != 'application/activity+json' and headers['content-type'] != 'application/ld+json':
        return False

    if headers['user-agent'] in banned_user_agents():
        return False

    if instance_blocked(headers['host']):
        return False

    return validate_header_signature(body, headers['host'], headers['date'], headers['signature'])


def validate_header_signature(body: str, host: str, date: str, signature: str) -> bool:
    body = json.loads(body)
    signature = parse_signature_header(signature)

    key_domain = urlparse(signature['key_id']).hostname
    id_domain = urlparse(body['id']).hostname

    if urlparse(body['object']['attributedTo']).hostname != key_domain:
        raise Exception('Invalid host url.')

    if key_domain != id_domain:
        raise Exception('Wrong domain.')

    user = find_actor_or_create(body['actor'])
    return verify_signature(user.private_key, signature, headers)


def banned_user_agents():
    return []  # todo: finish this function


@cache.cached(150)
def instance_blocked(host: str) -> bool:
    host = host.lower()
    if 'https://' in host or 'http://' in host:
        host = urlparse(host).hostname
    instance = BannedInstances.query.filter_by(domain=host.strip()).first()
    return instance is not None


def find_actor_or_create(actor: str) -> Union[User, Community, None]:
    user = None
    # actor parameter must be formatted as https://server/u/actor or https://server/c/actor
    if current_app.config['SERVER_NAME'] + '/c/' in actor:
        return Community.query.filter_by(
            ap_profile_id=actor).first()  # finds communities formatted like https://localhost/c/*

    if current_app.config['SERVER_NAME'] + '/u/' in actor:
        user = User.query.filter_by(username=actor.split('/')[-1], ap_id=None).first()  # finds local users
        if user is None:
            return None
    elif actor.startswith('https://'):
        server, address = extract_domain_and_actor(actor)
        if instance_blocked(server):
            return None
        user = User.query.filter_by(
            ap_profile_id=actor).first()  # finds users formatted like https://kbin.social/u/tables
        if user is None:
            user = Community.query.filter_by(ap_profile_id=actor).first()
    if user is None:
        # retrieve user details via webfinger, etc
        # todo: try, except block around every get_request
        webfinger_data = get_request(f"https://{server}/.well-known/webfinger",
                                     params={'resource': f"acct:{address}@{server}"})
        if webfinger_data.status_code == 200:
            webfinger_json = webfinger_data.json()
            for links in webfinger_json['links']:
                if 'rel' in links and links['rel'] == 'self':  # this contains the URL of the activitypub profile
                    type = links['type'] if 'type' in links else 'application/activity+json'
                    # retrieve the activitypub profile
                    actor_data = get_request(links['href'], headers={'Accept': type})
                    # to see the structure of the json contained in actor_data, do a GET to https://lemmy.world/c/technology with header Accept: application/activity+json
                    if actor_data.status_code == 200:
                        activity_json = actor_data.json()
                        if activity_json['type'] == 'Person':
                            user = User(user_name=activity_json['preferredUsername'],
                                        email=f"{address}@{server}",
                                        about=parse_summary(activity_json),
                                        created_at=activity_json['published'],
                                        ap_id=f"{address}@{server}",
                                        ap_public_url=activity_json['id'],
                                        ap_profile_id=activity_json['id'],
                                        ap_inbox_url=activity_json['endpoints']['sharedInbox'],
                                        ap_preferred_username=activity_json['preferredUsername'],
                                        ap_fetched_at=datetime.utcnow(),
                                        ap_domain=server,
                                        public_key=activity_json['publicKey']['publicKeyPem'],
                                        # language=community_json['language'][0]['identifier'] # todo: language
                                        )
                            if 'icon' in activity_json:
                                # todo: retrieve icon, save to disk, save more complete File record
                                avatar = File(source_url=activity_json['icon']['url'])
                                user.avatar = avatar
                                db.session.add(avatar)
                            if 'image' in activity_json:
                                # todo: retrieve image, save to disk, save more complete File record
                                cover = File(source_url=activity_json['image']['url'])
                                user.cover = cover
                                db.session.add(cover)
                            db.session.add(user)
                            db.session.commit()
                            return user
                        elif activity_json['type'] == 'Group':
                            community = Community(name=activity_json['preferredUsername'],
                                                  title=activity_json['name'],
                                                  description=activity_json['summary'],
                                                  nsfw=activity_json['sensitive'],
                                                  restricted_to_mods=activity_json['postingRestrictedToMods'],
                                                  created_at=activity_json['published'],
                                                  last_active=activity_json['updated'],
                                                  ap_id=f"{address[1:]}",
                                                  ap_public_url=activity_json['id'],
                                                  ap_profile_id=activity_json['id'],
                                                  ap_followers_url=activity_json['followers'],
                                                  ap_inbox_url=activity_json['endpoints']['sharedInbox'],
                                                  ap_fetched_at=datetime.utcnow(),
                                                  ap_domain=server,
                                                  public_key=activity_json['publicKey']['publicKeyPem'],
                                                  # language=community_json['language'][0]['identifier'] # todo: language
                                                  )
                            if 'icon' in activity_json:
                                # todo: retrieve icon, save to disk, save more complete File record
                                icon = File(source_url=activity_json['icon']['url'])
                                community.icon = icon
                                db.session.add(icon)
                            if 'image' in activity_json:
                                # todo: retrieve image, save to disk, save more complete File record
                                image = File(source_url=activity_json['image']['url'])
                                community.image = image
                                db.session.add(image)
                            db.session.add(community)
                            db.session.commit()
                            return community
        return None
    else:
        return user


def extract_domain_and_actor(url_string: str):
    # Parse the URL
    parsed_url = urlparse(url_string)

    # Extract the server domain name
    server_domain = parsed_url.netloc

    # Extract the part of the string after the last '/' character
    actor = parsed_url.path.split('/')[-1]

    return server_domain, actor


# create a summary from markdown if present, otherwise use html if available
def parse_summary(user_json) -> str:
    if 'source' in user_json and user_json['source'].get('mediaType') == 'text/markdown':
        # Convert Markdown to HTML
        markdown_text = user_json['source']['content']
        html_content = markdown2.markdown(markdown_text)
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
        parent_comment_id = parent_comment.id
        post_id = parent_comment.post_id
        root_id = parent_comment.root_id
    elif 'post' in in_reply_to:
        parent_comment_id = None
        post = Post.get_by_ap_id(in_reply_to)
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
