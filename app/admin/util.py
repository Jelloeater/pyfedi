from flask import request, abort, g, current_app, json
from app import db, cache, celery
from app.activitypub.signature import post_request
from app.activitypub.util import default_context
from app.models import User, Community, Instance, Site, ActivityPubLog, CommunityMember
from app.utils import gibberish


def unsubscribe_from_everything_then_delete(user_id):
    if current_app.debug:
        unsubscribe_from_everything_then_delete_task(user_id)
    else:
        unsubscribe_from_everything_then_delete_task.delay(user_id)


@celery.task
def unsubscribe_from_everything_then_delete_task(user_id):
    user = User.query.get(user_id)
    if user:
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
                    post_request(instance.inbox, payload, site.private_key,
                                 f"https://{current_app.config['SERVER_NAME']}#main-key")

        user.deleted = True
        user.delete_dependencies()
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
