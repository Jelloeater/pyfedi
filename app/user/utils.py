from time import sleep

from flask import current_app, json

from app import celery, db
from app.activitypub.signature import post_request
from app.activitypub.util import default_context
from app.community.util import send_to_remote_instance
from app.models import User, CommunityMember, Community, Instance, Site, utcnow, ActivityPubLog
from app.utils import gibberish, ap_datetime, instance_banned


def purge_user_then_delete(user_id):
    if current_app.debug:
        purge_user_then_delete_task(user_id)
    else:
        purge_user_then_delete_task.delay(user_id)


@celery.task
def purge_user_then_delete_task(user_id):
    user = User.query.get(user_id)
    if user:
        # posts
        for post in user.posts:
            if not post.community.local_only:
                delete_json = {
                    'id': f"https://{current_app.config['SERVER_NAME']}/activities/delete/{gibberish(15)}",
                    'type': 'Delete',
                    'actor': user.profile_id(),
                    'audience': post.community.profile_id(),
                    'to': [post.community.profile_id(), 'https://www.w3.org/ns/activitystreams#Public'],
                    'published': ap_datetime(utcnow()),
                    'cc': [
                        user.followers_url()
                    ],
                    'object': post.ap_id,
                }

                if not post.community.is_local():  # this is a remote community, send it to the instance that hosts it
                    success = post_request(post.community.ap_inbox_url, delete_json, user.private_key,
                                           user.ap_profile_id + '#main-key')

                else:  # local community - send it to followers on remote instances, using Announce
                    announce = {
                        "id": f"https://{current_app.config['SERVER_NAME']}/activities/announce/{gibberish(15)}",
                        "type": 'Announce',
                        "to": [
                            "https://www.w3.org/ns/activitystreams#Public"
                        ],
                        "actor": post.community.ap_profile_id,
                        "cc": [
                            post.community.ap_followers_url
                        ],
                        '@context': default_context(),
                        'object': delete_json
                    }

                    for instance in post.community.following_instances():
                        if instance.inbox and not instance_banned(instance.domain):
                            send_to_remote_instance(instance.id, post.community.id, announce)

        # unsubscribe
        communities = CommunityMember.query.filter_by(user_id=user_id).all()
        for membership in communities:
            community = Community.query.get(membership.community_id)
            unsubscribe_from_community(community, user)

        # federate deletion of account
        if user.is_local():
            instances = Instance.query.all()
            site = Site.query.get(1)
            payload = {
                "@context": default_context(),
                "actor": user.ap_profile_id,
                "id": f"{user.ap_profile_id}#delete",
                "object": user.ap_profile_id,
                "to": [
                    "https://www.w3.org/ns/activitystreams#Public"
                ],
                "type": "Delete"
            }
            for instance in instances:
                if instance.inbox and instance.id != 1:
                    post_request(instance.inbox, payload, user.private_key, user.ap_profile_id + '#main-key')

        sleep(100)                                  # wait a while for any related activitypub traffic to die down.
        user.deleted = True
        user.delete_dependencies()
        user.purge_content()
        db.session.commit()


def unsubscribe_from_community(community, user):
    undo_id = f"https://{current_app.config['SERVER_NAME']}/activities/undo/" + gibberish(15)
    follow = {
        "actor": f"https://{current_app.config['SERVER_NAME']}/u/{user.user_name}",
        "to": [community.ap_profile_id],
        "object": community.ap_profile_id,
        "type": "Follow",
        "id": f"https://{current_app.config['SERVER_NAME']}/activities/follow/{gibberish(15)}"
    }
    undo = {
        'actor': user.profile_id(),
        'to': [community.ap_profile_id],
        'type': 'Undo',
        'id': undo_id,
        'object': follow
    }
    activity = ActivityPubLog(direction='out', activity_id=undo_id, activity_type='Undo',
                              activity_json=json.dumps(undo), result='processing')
    db.session.add(activity)
    db.session.commit()
    post_request(community.ap_inbox_url, undo, user.private_key, user.profile_id() + '#main-key')
    activity.result = 'success'
    db.session.commit()