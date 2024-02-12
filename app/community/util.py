from datetime import datetime, timedelta
from threading import Thread
from time import sleep
from typing import List
import requests
from PIL import Image, ImageOps
from flask import request, abort, g, current_app
from flask_login import current_user
from pillow_heif import register_heif_opener

from app import db, cache, celery
from app.activitypub.signature import post_request
from app.activitypub.util import find_actor_or_create, actor_json_to_model, post_json_to_model
from app.constants import POST_TYPE_ARTICLE, POST_TYPE_LINK, POST_TYPE_IMAGE
from app.models import Community, File, BannedInstances, PostReply, PostVote, Post, utcnow, CommunityMember, Site, \
    Instance, Notification, User
from app.utils import get_request, gibberish, markdown_to_html, domain_from_url, allowlist_html, \
    html_to_markdown, is_image_url, ensure_directory_exists, inbox_domain, post_ranking, shorten_string, parse_page
from sqlalchemy import func
import os


allowed_extensions = ['.gif', '.jpg', '.jpeg', '.png', '.webp', '.heic']


def search_for_community(address: str):
    if address.startswith('!'):
        name, server = address[1:].split('@')

        banned = BannedInstances.query.filter_by(domain=server).first()
        if banned:
            reason = f" Reason: {banned.reason}" if banned.reason is not None else ''
            raise Exception(f"{server} is blocked.{reason}")  # todo: create custom exception class hierarchy

        already_exists = Community.query.filter_by(ap_id=address[1:]).first()
        if already_exists:
            return already_exists

        # Look up the profile address of the community using WebFinger
        # todo: try, except block around every get_request
        webfinger_data = get_request(f"https://{server}/.well-known/webfinger",
                                     params={'resource': f"acct:{address[1:]}"})
        if webfinger_data.status_code == 200:
            webfinger_json = webfinger_data.json()
            for links in webfinger_json['links']:
                if 'rel' in links and links['rel'] == 'self':  # this contains the URL of the activitypub profile
                    type = links['type'] if 'type' in links else 'application/activity+json'
                    # retrieve the activitypub profile
                    community_data = get_request(links['href'], headers={'Accept': type})
                    # to see the structure of the json contained in community_data, do a GET to https://lemmy.world/c/technology with header Accept: application/activity+json
                    if community_data.status_code == 200:
                        community_json = community_data.json()
                        community_data.close()
                        if community_json['type'] == 'Group':
                            community = actor_json_to_model(community_json, name, server)
                            if community:
                                if current_app.debug:
                                    retrieve_mods_and_backfill(community.id)
                                else:
                                    retrieve_mods_and_backfill.delay(community.id)
                            return community
        return None


@celery.task
def retrieve_mods_and_backfill(community_id: int):
    with current_app.app_context():
        community = Community.query.get(community_id)
        site = Site.query.get(1)
        if community.ap_moderators_url:
            mods_request = get_request(community.ap_moderators_url, headers={'Accept': 'application/activity+json'})
            if mods_request.status_code == 200:
                mods_data = mods_request.json()
                mods_request.close()
                if mods_data and mods_data['type'] == 'OrderedCollection' and 'orderedItems' in mods_data:
                    for actor in mods_data['orderedItems']:
                        sleep(0.5)
                        user = find_actor_or_create(actor)
                        if user:
                            existing_membership = CommunityMember.query.filter_by(community_id=community.id, user_id=user.id).first()
                            if existing_membership:
                                existing_membership.is_moderator = True
                            else:
                                new_membership = CommunityMember(community_id=community.id, user_id=user.id, is_moderator=True)
                                db.session.add(new_membership)
                    db.session.commit()

        # only backfill nsfw if nsfw communities are allowed
        if (community.nsfw and not site.enable_nsfw) or (community.nsfl and not site.enable_nsfl):
            return

        # download 50 old posts
        if community.ap_public_url:
            outbox_request = get_request(community.ap_public_url + '/outbox', headers={'Accept': 'application/activity+json'})
            if outbox_request.status_code == 200:
                outbox_data = outbox_request.json()
                outbox_request.close()
                if outbox_data['type'] == 'OrderedCollection' and 'orderedItems' in outbox_data:
                    activities_processed = 0
                    for activity in outbox_data['orderedItems']:
                        user = find_actor_or_create(activity['object']['actor'])
                        if user:
                            post = post_json_to_model(activity['object']['object'], user, community)
                            post.ap_create_id = activity['object']['id']
                            post.ap_announce_id = activity['id']
                            post.ranking = post_ranking(post.score, post.posted_at)
                            db.session.commit()

                        activities_processed += 1
                        if activities_processed >= 50:
                            break
                    c = Community.query.get(community.id)
                    c.post_count = activities_processed
                    c.last_active = site.last_active = utcnow()
                    db.session.commit()


def community_url_exists(url) -> bool:
    community = Community.query.filter(Community.ap_profile_id == url.lower()).first()
    return community is not None


def actor_to_community(actor) -> Community:
    actor = actor.strip()
    if '@' in actor:
        community = Community.query.filter_by(banned=False, ap_id=actor).first()
    else:
        community = Community.query.filter(func.lower(Community.name) == func.lower(actor)).filter_by(banned=False, ap_id=None).first()
    return community


def opengraph_parse(url):
    if '?' in url:
        url = url.split('?')
        url = url[0]
    try:
        return parse_page(url)
    except Exception as ex:
        return None


def url_to_thumbnail_file(filename) -> File:
    filename_for_extension = filename.split('?')[0] if '?' in filename else filename
    unused, file_extension = os.path.splitext(filename_for_extension)
    response = requests.get(filename, timeout=5)
    if response.status_code == 200:
        new_filename = gibberish(15)
        directory = 'app/static/media/posts/' + new_filename[0:2] + '/' + new_filename[2:4]
        ensure_directory_exists(directory)
        final_place = os.path.join(directory, new_filename + file_extension)
        with open(final_place, 'wb') as f:
            f.write(response.content)
        response.close()
        Image.MAX_IMAGE_PIXELS = 89478485
        with Image.open(final_place) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((150, 150))
            img.save(final_place)
            thumbnail_width = img.width
            thumbnail_height = img.height
        return File(file_name=new_filename + file_extension, thumbnail_width=thumbnail_width,
                    thumbnail_height=thumbnail_height, thumbnail_path=final_place,
                    source_url=filename)


def save_post(form, post: Post):
    post.nsfw = form.nsfw.data
    post.nsfl = form.nsfl.data
    post.notify_author = form.notify_author.data
    if form.post_type.data == '' or form.post_type.data == 'discussion':
        post.title = form.discussion_title.data
        post.body = form.discussion_body.data
        post.body_html = markdown_to_html(post.body)
        post.type = POST_TYPE_ARTICLE
    elif form.post_type.data == 'link':
        post.title = form.link_title.data
        post.body = form.link_body.data
        post.body_html = markdown_to_html(post.body)
        url_changed = post.id is None or form.link_url.data != post.url
        post.url = form.link_url.data
        post.type = POST_TYPE_LINK
        domain = domain_from_url(form.link_url.data)
        domain.post_count += 1
        post.domain = domain

        if url_changed:
            if post.image_id:
                remove_old_file(post.image_id)
                post.image_id = None

            unused, file_extension = os.path.splitext(form.link_url.data)  # do not use _ here instead of 'unused'
            # this url is a link to an image - generate a thumbnail of it
            if file_extension.lower() in allowed_extensions:
                file = url_to_thumbnail_file(form.link_url.data)
                if file:
                    post.image = file
                    db.session.add(file)
            else:
                # check opengraph tags on the page and make a thumbnail if an image is available in the og:image meta tag
                opengraph = opengraph_parse(form.link_url.data)
                if opengraph and (opengraph.get('og:image', '') != '' or opengraph.get('og:image:url', '') != ''):
                    filename = opengraph.get('og:image') or opengraph.get('og:image:url')
                    filename_for_extension = filename.split('?')[0] if '?' in filename else filename
                    unused, file_extension = os.path.splitext(filename_for_extension)
                    if file_extension.lower() in allowed_extensions:
                        file = url_to_thumbnail_file(filename)
                        if file:
                            file.alt_text = opengraph.get('og:title')
                            post.image = file
                            db.session.add(file)

    elif form.post_type.data == 'image':
        post.title = form.image_title.data
        post.body = form.image_body.data
        post.body_html = markdown_to_html(post.body)
        post.type = POST_TYPE_IMAGE
        alt_text = form.image_alt_text.data if form.image_alt_text.data else form.image_title.data
        uploaded_file = request.files['image_file']
        if uploaded_file and uploaded_file.filename != '':
            if post.image_id:
                remove_old_file(post.image_id)
                post.image_id = None

            # check if this is an allowed type of file
            file_ext = os.path.splitext(uploaded_file.filename)[1]
            if file_ext.lower() not in allowed_extensions:
                abort(400)
            new_filename = gibberish(15)

            # set up the storage directory
            directory = 'app/static/media/posts/' + new_filename[0:2] + '/' + new_filename[2:4]
            ensure_directory_exists(directory)

            # save the file
            final_place = os.path.join(directory, new_filename + file_ext)
            final_place_thumbnail = os.path.join(directory, new_filename + '_thumbnail.webp')
            uploaded_file.seek(0)
            uploaded_file.save(final_place)

            if file_ext.lower() == '.heic':
                register_heif_opener()

            Image.MAX_IMAGE_PIXELS = 89478485

            # resize if necessary
            img = Image.open(final_place)
            if '.' + img.format.lower() in allowed_extensions:
                img = ImageOps.exif_transpose(img)
                img_width = img.width
                img_height = img.height
                if img.width > 2000 or img.height > 2000:
                    img.thumbnail((2000, 2000))
                    img.save(final_place)
                    img_width = img.width
                    img_height = img.height
                # save a second, smaller, version as a thumbnail
                img.thumbnail((256, 256))
                img.save(final_place_thumbnail, format="WebP", quality=93)
                thumbnail_width = img.width
                thumbnail_height = img.height

                file = File(file_path=final_place, file_name=new_filename + file_ext, alt_text=alt_text,
                            width=img_width, height=img_height, thumbnail_width=thumbnail_width,
                            thumbnail_height=thumbnail_height, thumbnail_path=final_place_thumbnail,
                            source_url=final_place.replace('app/static/', f"https://{current_app.config['SERVER_NAME']}/static/"))
                post.image = file
                db.session.add(file)

    elif form.post_type.data == 'poll':
        ...
    else:
        raise Exception('invalid post type')
    if post.id is None:
        if current_user.reputation > 100:
            post.up_votes = 1
            post.score = 1
        if current_user.reputation < -100:
            post.score = -1
        post.ranking = post_ranking(post.score, utcnow())
        db.session.add(post)

    g.site.last_active = utcnow()


def remove_old_file(file_id):
    remove_file = File.query.get(file_id)
    remove_file.delete_from_disk()


def save_icon_file(icon_file, directory='communities') -> File:
    # check if this is an allowed type of file
    file_ext = os.path.splitext(icon_file.filename)[1]
    if file_ext.lower() not in allowed_extensions:
        abort(400)
    new_filename = gibberish(15)

    # set up the storage directory
    directory = f'app/static/media/{directory}/' + new_filename[0:2] + '/' + new_filename[2:4]
    ensure_directory_exists(directory)

    # save the file
    final_place = os.path.join(directory, new_filename + file_ext)
    final_place_thumbnail = os.path.join(directory, new_filename + '_thumbnail.webp')
    icon_file.save(final_place)

    if file_ext.lower() == '.heic':
        register_heif_opener()

    # resize if necessary
    Image.MAX_IMAGE_PIXELS = 89478485
    img = Image.open(final_place)
    if '.' + img.format.lower() in allowed_extensions:
        img = ImageOps.exif_transpose(img)
        img_width = img.width
        img_height = img.height
        if img.width > 250 or img.height > 250:
            img.thumbnail((250, 250))
            img.save(final_place)
            img_width = img.width
            img_height = img.height
        # save a second, smaller, version as a thumbnail
        img.thumbnail((40, 40))
        img.save(final_place_thumbnail, format="WebP", quality=93)
        thumbnail_width = img.width
        thumbnail_height = img.height

        file = File(file_path=final_place, file_name=new_filename + file_ext, alt_text=f'{directory} icon',
                    width=img_width, height=img_height, thumbnail_width=thumbnail_width,
                    thumbnail_height=thumbnail_height, thumbnail_path=final_place_thumbnail)
        db.session.add(file)
        return file
    else:
        abort(400)


def save_banner_file(banner_file, directory='communities') -> File:
    # check if this is an allowed type of file
    file_ext = os.path.splitext(banner_file.filename)[1]
    if file_ext.lower() not in allowed_extensions:
        abort(400)
    new_filename = gibberish(15)

    # set up the storage directory
    directory = f'app/static/media/{directory}/' + new_filename[0:2] + '/' + new_filename[2:4]
    ensure_directory_exists(directory)

    # save the file
    final_place = os.path.join(directory, new_filename + file_ext)
    final_place_thumbnail = os.path.join(directory, new_filename + '_thumbnail.webp')
    banner_file.save(final_place)

    if file_ext.lower() == '.heic':
        register_heif_opener()

    # resize if necessary
    Image.MAX_IMAGE_PIXELS = 89478485
    img = Image.open(final_place)
    if '.' + img.format.lower() in allowed_extensions:
        img = ImageOps.exif_transpose(img)
        img_width = img.width
        img_height = img.height
        if img.width > 1600 or img.height > 600:
            img.thumbnail((1600, 600))
            img.save(final_place)
            img_width = img.width
            img_height = img.height

        # save a second, smaller, version as a thumbnail
        img.thumbnail((878, 500))
        img.save(final_place_thumbnail, format="WebP", quality=93)
        thumbnail_width = img.width
        thumbnail_height = img.height

        file = File(file_path=final_place, file_name=new_filename + file_ext, alt_text=f'{directory} banner',
                    width=img_width, height=img_height, thumbnail_path=final_place_thumbnail,
                    thumbnail_width=thumbnail_width, thumbnail_height=thumbnail_height)
        db.session.add(file)
        return file
    else:
        abort(400)


# NB this always signs POSTs as the community so is only suitable for Announce activities
def send_to_remote_instance(instance_id: int, community_id: int, payload):
    if current_app.debug:
        send_to_remote_instance_task(instance_id, community_id, payload)
    else:
        send_to_remote_instance_task.delay(instance_id, community_id, payload)


@celery.task
def send_to_remote_instance_task(instance_id: int, community_id: int, payload):
    community = Community.query.get(community_id)
    if community:
        instance = Instance.query.get(instance_id)
        if post_request(instance.inbox, payload, community.private_key, community.ap_profile_id + '#main-key'):
            instance.last_successful_send = utcnow()
            instance.failures = 0
        else:
            instance.failures += 1
            instance.most_recent_attempt = utcnow()
            instance.start_trying_again = utcnow() + timedelta(seconds=instance.failures ** 4)
            if instance.failures > 2:
                instance.dormant = True
        db.session.commit()

