from datetime import datetime
from typing import List

import requests
from PIL import Image, ImageOps
from flask import request, abort
from flask_login import current_user
from pillow_heif import register_heif_opener

from app import db, cache
from app.constants import POST_TYPE_ARTICLE, POST_TYPE_LINK, POST_TYPE_IMAGE
from app.models import Community, File, BannedInstances, PostReply, PostVote, Post
from app.utils import get_request, gibberish, markdown_to_html, domain_from_url, validate_image
from sqlalchemy import desc, text
import os
from opengraph_parse import parse_page


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
                        if community_json['type'] == 'Group':
                            community = Community(name=community_json['preferredUsername'],
                                                  title=community_json['name'],
                                                  description=community_json['summary'],
                                                  nsfw=community_json['sensitive'],
                                                  restricted_to_mods=community_json['postingRestrictedToMods'],
                                                  created_at=community_json['published'],
                                                  last_active=community_json['updated'],
                                                  ap_id=f"{address[1:]}",
                                                  ap_public_url=community_json['id'],
                                                  ap_profile_id=community_json['id'],
                                                  ap_followers_url=community_json['followers'],
                                                  ap_inbox_url=community_json['endpoints']['sharedInbox'],
                                                  ap_moderators_url=community_json['attributedTo'] if 'attributedTo' in community_json else None,
                                                  ap_fetched_at=datetime.utcnow(),
                                                  ap_domain=server,
                                                  public_key=community_json['publicKey']['publicKeyPem'],
                                                  # language=community_json['language'][0]['identifier'] # todo: language
                                                  )
                            if 'icon' in community_json:
                                # todo: retrieve icon, save to disk, save more complete File record
                                icon = File(source_url=community_json['icon']['url'])
                                community.icon = icon
                                db.session.add(icon)
                            if 'image' in community_json:
                                # todo: retrieve image, save to disk, save more complete File record
                                image = File(source_url=community_json['image']['url'])
                                community.image = image
                                db.session.add(image)
                            db.session.add(community)
                            db.session.commit()
                            return community
        return None


def community_url_exists(url) -> bool:
    community = Community.query.filter_by(ap_profile_id=url).first()
    return community is not None


def actor_to_community(actor) -> Community:
    actor = actor.strip()
    if '@' in actor:
        community = Community.query.filter_by(banned=False, ap_id=actor).first()
    else:
        community = Community.query.filter_by(name=actor, banned=False, ap_id=None).first()
    return community


def ensure_directory_exists(directory):
    parts = directory.split('/')
    rebuild_directory = ''
    for part in parts:
        rebuild_directory += part
        if not os.path.isdir(rebuild_directory):
            os.mkdir(rebuild_directory)
        rebuild_directory += '/'


@cache.memoize(timeout=50)
def opengraph_parse(url):
    try:
        return parse_page(url)
    except Exception as ex:
        return None


def url_to_thumbnail_file(filename) -> File:
    unused, file_extension = os.path.splitext(filename)
    response = requests.get(filename, timeout=5)
    if response.status_code == 200:
        new_filename = gibberish(15)
        directory = 'app/static/media/posts/' + new_filename[0:2] + '/' + new_filename[2:4]
        ensure_directory_exists(directory)
        final_place = os.path.join(directory, new_filename + file_extension)
        with open(final_place, 'wb') as f:
            f.write(response.content)
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
    if form.type.data == '' or form.type.data == 'discussion':
        post.title = form.discussion_title.data
        post.body = form.discussion_body.data
        post.body_html = markdown_to_html(post.body)
        post.type = POST_TYPE_ARTICLE
    elif form.type.data == 'link':
        post.title = form.link_title.data
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
            valid_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
            unused, file_extension = os.path.splitext(form.link_url.data)  # do not use _ here instead of 'unused'
            # this url is a link to an image - generate a thumbnail of it
            if file_extension in valid_extensions:
                file = url_to_thumbnail_file(form.link_url.data)
                if file:
                    post.image = file
                    db.session.add(file)
            else:
                # check opengraph tags on the page and make a thumbnail if an image is available in the og:image meta tag
                opengraph = opengraph_parse(form.link_url.data)
                if opengraph and opengraph.get('og:image', '') != '':
                    filename = opengraph.get('og:image')
                    valid_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
                    unused, file_extension = os.path.splitext(filename)
                    if file_extension.lower() in valid_extensions:
                        file = url_to_thumbnail_file(filename)
                        if file:
                            file.alt_text = opengraph.get('og:title')
                            post.image = file
                            db.session.add(file)

    elif form.type.data == 'image':
        post.title = form.image_title.data
        post.type = POST_TYPE_IMAGE
        uploaded_file = request.files['image_file']
        if uploaded_file and uploaded_file.filename != '':
            if post.image_id:
                remove_old_file(post.image_id)
                post.image_id = None

            # check if this is an allowed type of file
            file_ext = os.path.splitext(uploaded_file.filename)[1]
            if file_ext.lower() not in allowed_extensions or file_ext != validate_image(
                    uploaded_file.stream):
                abort(400)
            new_filename = gibberish(15)

            # set up the storage directory
            directory = 'app/static/media/posts/' + new_filename[0:2] + '/' + new_filename[2:4]
            ensure_directory_exists(directory)

            # save the file
            final_place = os.path.join(directory, new_filename + file_ext)
            final_place_thumbnail = os.path.join(directory, new_filename + '_thumbnail.webp')
            uploaded_file.save(final_place)

            if file_ext.lower() == '.heic':
                register_heif_opener()

            # resize if necessary
            img = Image.open(final_place)
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

            file = File(file_path=final_place, file_name=new_filename + file_ext, alt_text=form.image_title.data,
                        width=img_width, height=img_height, thumbnail_width=thumbnail_width,
                        thumbnail_height=thumbnail_height, thumbnail_path=final_place_thumbnail)
            post.image = file
            db.session.add(file)

    elif form.type.data == 'poll':
        ...
    else:
        raise Exception('invalid post type')
    if post.id is None:
        postvote = PostVote(user_id=current_user.id, author_id=current_user.id, post=post, effect=1.0)
        post.up_votes = 1
        post.score = 1
        db.session.add(postvote)
        db.session.add(post)


def remove_old_file(file_id):
    remove_file = File.query.get(file_id)
    remove_file.delete_from_disk()


def save_icon_file(icon_file) -> File:
    # check if this is an allowed type of file
    file_ext = os.path.splitext(icon_file.filename)[1]
    if file_ext.lower() not in allowed_extensions or file_ext != validate_image(
            icon_file.stream):
        abort(400)
    new_filename = gibberish(15)

    # set up the storage directory
    directory = 'app/static/media/communities/' + new_filename[0:2] + '/' + new_filename[2:4]
    ensure_directory_exists(directory)

    # save the file
    final_place = os.path.join(directory, new_filename + file_ext)
    final_place_thumbnail = os.path.join(directory, new_filename + '_thumbnail.webp')
    icon_file.save(final_place)

    if file_ext.lower() == '.heic':
        register_heif_opener()

    # resize if necessary
    img = Image.open(final_place)
    img = ImageOps.exif_transpose(img)
    img_width = img.width
    img_height = img.height
    if img.width > 200 or img.height > 200:
        img.thumbnail((200, 200))
        img.save(final_place)
        img_width = img.width
        img_height = img.height
    # save a second, smaller, version as a thumbnail
    img.thumbnail((32, 32))
    img.save(final_place_thumbnail, format="WebP", quality=93)
    thumbnail_width = img.width
    thumbnail_height = img.height

    file = File(file_path=final_place, file_name=new_filename + file_ext, alt_text='community icon',
                width=img_width, height=img_height, thumbnail_width=thumbnail_width,
                thumbnail_height=thumbnail_height, thumbnail_path=final_place_thumbnail)
    db.session.add(file)
    return file


def save_banner_file(banner_file) -> File:
    # check if this is an allowed type of file
    file_ext = os.path.splitext(banner_file.filename)[1]
    if file_ext.lower() not in allowed_extensions or file_ext != validate_image(
            banner_file.stream):
        abort(400)
    new_filename = gibberish(15)

    # set up the storage directory
    directory = 'app/static/media/communities/' + new_filename[0:2] + '/' + new_filename[2:4]
    ensure_directory_exists(directory)

    # save the file
    final_place = os.path.join(directory, new_filename + file_ext)
    final_place_thumbnail = os.path.join(directory, new_filename + '_thumbnail.webp')
    banner_file.save(final_place)

    if file_ext.lower() == '.heic':
        register_heif_opener()

    # resize if necessary
    img = Image.open(final_place)
    img = ImageOps.exif_transpose(img)
    img_width = img.width
    img_height = img.height
    if img.width > 1000 or img.height > 300:
        img.thumbnail((1000, 300))
        img.save(final_place)
        img_width = img.width
        img_height = img.height

    file = File(file_path=final_place, file_name=new_filename + file_ext, alt_text='community banner',
                width=img_width, height=img_height)
    db.session.add(file)
    return file