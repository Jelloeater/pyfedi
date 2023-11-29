from datetime import datetime
from typing import List

import requests
from PIL import Image, ImageOps

from app import db, cache
from app.models import Community, File, BannedInstances, PostReply
from app.utils import get_request, gibberish
from sqlalchemy import desc, text
import os
from opengraph_parse import parse_page


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


# replies to a post, in a tree, sorted by a variety of methods
def post_replies(post_id: int, sort_by: str, show_first: int = 0) -> List[PostReply]:
    comments = PostReply.query.filter_by(post_id=post_id)
    if sort_by == 'hot':
        comments = comments.order_by(desc(PostReply.ranking))
    elif sort_by == 'top':
        comments = comments.order_by(desc(PostReply.score))
    elif sort_by == 'new':
        comments = comments.order_by(desc(PostReply.posted_at))

    comments_dict = {comment.id: {'comment': comment, 'replies': []} for comment in comments.all()}

    for comment in comments:
        if comment.parent_id is not None:
            parent_comment = comments_dict.get(comment.parent_id)
            if parent_comment:
                parent_comment['replies'].append(comments_dict[comment.id])

    return [comment for comment in comments_dict.values() if comment['comment'].parent_id is None]


def get_comment_branch(post_id: int, comment_id: int, sort_by: str) -> List[PostReply]:
    # Fetch the specified parent comment and its replies
    parent_comment = PostReply.query.get(comment_id)
    if parent_comment is None:
        return []

    comments = PostReply.query.filter(PostReply.post_id == post_id)
    if sort_by == 'hot':
        comments = comments.order_by(desc(PostReply.ranking))
    elif sort_by == 'top':
        comments = comments.order_by(desc(PostReply.score))
    elif sort_by == 'new':
        comments = comments.order_by(desc(PostReply.posted_at))

    comments_dict = {comment.id: {'comment': comment, 'replies': []} for comment in comments.all()}

    for comment in comments:
        if comment.parent_id is not None:
            parent_comment = comments_dict.get(comment.parent_id)
            if parent_comment:
                parent_comment['replies'].append(comments_dict[comment.id])

    return [comment for comment in comments_dict.values() if comment['comment'].id == comment_id]


# The number of replies a post has
def post_reply_count(post_id) -> int:
    return db.session.execute(text('SELECT COUNT(id) as c FROM "post_reply" WHERE post_id = :post_id'),
                              {'post_id': post_id}).scalar()


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
