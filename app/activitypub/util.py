import json
import os
from flask import current_app
from sqlalchemy import text
from app import db
from app.models import User, Post, Community, BannedInstances
import time
import base64
import requests
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from app.constants import *
import functools
from urllib.parse import urlparse


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
    return []   # todo: finish this function


@functools.lru_cache(maxsize=100)
def instance_blocked(host):
    instance = BannedInstances.query.filter_by(domain=host.strip()).first()
    return instance is not None


def find_actor_or_create(actor):
    if current_app.config['SERVER_NAME'] + '/c/' in actor:
        return Community.query.filter_by(name=actor).first()  # finds communities formatted like https://localhost/c/*

    user = User.query.filter_by(ap_profile_id=actor).first() # finds users formatted like https://kbin.social/u/tables
    if user is None:
        # todo: retrieve user details via webfinger, etc
    else:
        return user
