from datetime import datetime

from app import db, constants, cache
from app.activitypub import bp
from flask import request, Response, current_app, abort, jsonify, json

from app.activitypub.signature import HttpSignature
from app.community.routes import show_community
from app.user.routes import show_profile
from app.constants import POST_TYPE_LINK, POST_TYPE_IMAGE, SUBSCRIPTION_MEMBER
from app.models import User, Community, CommunityJoinRequest, CommunityMember, CommunityBan, ActivityPubLog, Post, \
    PostReply, Instance, PostVote, PostReplyVote, File, AllowedInstances, BannedInstances
from app.activitypub.util import public_key, users_total, active_half_year, active_month, local_posts, local_comments, \
    post_to_activity, find_actor_or_create, default_context, instance_blocked, find_reply_parent, find_liked_object, \
    lemmy_site_data, instance_weight
from app.utils import gibberish, get_setting, is_image_url, allowlist_html, html_to_markdown, render_template, \
    domain_from_url, markdown_to_html, community_membership
import werkzeug.exceptions

INBOX = []


@bp.route('/.well-known/webfinger')
def webfinger():
    if request.args.get('resource'):
        query = request.args.get('resource')  # acct:alice@tada.club
        if 'acct:' in query:
            actor = query.split(':')[1].split('@')[0]  # alice
        elif 'https:' in query or 'http:' in query:
            actor = query.split('/')[-1]
        else:
            return 'Webfinger regex failed to match'

        seperator = 'u'
        type = 'Person'
        user = User.query.filter_by(user_name=actor.strip(), deleted=False, banned=False, ap_id=None).first()
        if user is None:
            community = Community.query.filter_by(name=actor.strip(), ap_id=None).first()
            if community is None:
                return ''
            seperator = 'c'
            type = 'Group'

        webfinger_data = {
            "subject": f"acct:{actor}@{current_app.config['SERVER_NAME']}",
            "aliases": [f"https://{current_app.config['SERVER_NAME']}/{seperator}/{actor}"],
            "links": [
                {
                    "rel": "http://webfinger.net/rel/profile-page",
                    "type": "text/html",
                    "href": f"https://{current_app.config['SERVER_NAME']}/{seperator}/{actor}"
                },
                {
                    "rel": "self",
                    "type": "application/activity+json",
                    "href": f"https://{current_app.config['SERVER_NAME']}/{seperator}/{actor}",
                    "properties": {
                        "https://www.w3.org/ns/activitystreams#type": type
                    }
                }
            ]
        }
        resp = jsonify(webfinger_data)
        resp.headers.add_header('Access-Control-Allow-Origin', '*')
        return resp
    else:
        abort(404)


@bp.route('/.well-known/nodeinfo')
def nodeinfo():
    nodeinfo_data = {"links": [{"rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
                                "href": f"https://{current_app.config['SERVER_NAME']}/nodeinfo/2.0"}]}
    return jsonify(nodeinfo_data)


@bp.route('/nodeinfo/2.0')
@bp.route('/nodeinfo/2.0.json')
def nodeinfo2():

    nodeinfo_data = {
                "version": "2.0",
                "software": {
                    "name": "PieFed",
                    "version": "0.1"
                },
                "protocols": [
                    "activitypub"
                ],
                "usage": {
                    "users": {
                        "total": users_total(),
                        "activeHalfyear": active_half_year(),
                        "activeMonth": active_month()
                    },
                    "localPosts": local_posts(),
                    "localComments": local_comments()
                },
                "openRegistrations": True
            }
    return jsonify(nodeinfo_data)


@bp.route('/api/v3/site')
def lemmy_site():
    return jsonify(lemmy_site_data())


@bp.route('/api/v3/federated_instances')
def lemmy_federated_instances():
    instances = Instance.query.all()
    linked = []
    allowed = []
    blocked = []
    for instance in instances:
        instance_data = {"id": instance.id, "domain": instance.domain, "published": instance.created_at.isoformat(), "updated": instance.updated_at.isoformat()}
        if instance.software:
            instance_data['software'] = instance.software
        if instance.version:
            instance_data['version'] = instance.version
        linked.append(instance_data)
    for instance in AllowedInstances.query.all():
        allowed.append({"id": instance.id, "domain": instance.domain, "published": datetime.utcnow(), "updated": datetime.utcnow()})
    for instance in BannedInstances.query.all():
        blocked.append({"id": instance.id, "domain": instance.domain, "published": datetime.utcnow(), "updated": datetime.utcnow()})
    return jsonify({
        "federated_instances": {
            "linked": linked,
            "allowed": allowed,
            "blocked": blocked
        }
    })


@bp.route('/u/<actor>', methods=['GET'])
def user_profile(actor):
    """ Requests to this endpoint can be for a JSON representation of the user, or a HTML rendering of their profile.
    The two types of requests are differentiated by the header """
    actor = actor.strip()
    if '@' in actor:
        user = User.query.filter_by(ap_id=actor, deleted=False, banned=False).first()
    else:
        user = User.query.filter_by(user_name=actor, deleted=False, banned=False, ap_id=None).first()

    if user is not None:
        if 'application/ld+json' in request.headers.get('Accept', '') or 'application/activity+json' in request.headers.get('Accept', ''):
            server = current_app.config['SERVER_NAME']
            actor_data = {  "@context": default_context(),
                            "type": "Person",
                            "id": f"https://{server}/u/{actor}",
                            "preferredUsername": actor,
                            "inbox": f"https://{server}/u/{actor}/inbox",
                            "outbox": f"https://{server}/u/{actor}/outbox",
                            "publicKey": {
                                "id": f"https://{server}/u/{actor}#main-key",
                                "owner": f"https://{server}/u/{actor}",
                                "publicKeyPem": user.public_key      # .replace("\n", "\\n")    #LOOKSWRONG
                            },
                            "endpoints": {
                                "sharedInbox": f"https://{server}/inbox"
                            },
                            "published": user.created.isoformat() + '+00:00',
                        }
            if user.avatar_id is not None:
                actor_data["icon"] = {
                    "type": "Image",
                    "url": f"https://{server}/avatars/{user.avatar.file_path}"
                }
            if user.about:
                actor_data['source'] = {
                    "content": user.about,
                    "mediaType": "text/markdown"
                }
                actor_data['summary'] = markdown_to_html(user.about)
            resp = jsonify(actor_data)
            resp.content_type = 'application/activity+json'
            return resp
        else:
            return show_profile(user)
    else:
        abort(404)


@bp.route('/c/<actor>', methods=['GET'])
def community_profile(actor):
    """ Requests to this endpoint can be for a JSON representation of the community, or a HTML rendering of it.
        The two types of requests are differentiated by the header """
    actor = actor.strip()
    if '@' in actor:
        # don't provide activitypub info for remote communities
        if 'application/ld+json' in request.headers.get('Accept', '') or 'application/activity+json' in request.headers.get('Accept', ''):
            abort(404)
        community: Community = Community.query.filter_by(ap_id=actor, banned=False).first()
    else:
        community: Community = Community.query.filter_by(name=actor, banned=False, ap_id=None).first()
    if community is not None:
        if 'application/ld+json' in request.headers.get('Accept', '') or 'application/activity+json' in request.headers.get('Accept', ''):
            server = current_app.config['SERVER_NAME']
            actor_data = {"@context": default_context(),
                "type": "Group",
                "id": f"https://{server}/c/{actor}",
                "name": community.title,
                "summary": community.description,
                "sensitive": True if community.nsfw or community.nsfl else False,
                "preferredUsername": actor,
                "inbox": f"https://{server}/c/{actor}/inbox",
                "outbox": f"https://{server}/c/{actor}/outbox",
                "followers": f"https://{server}/c/{actor}/followers",
                "moderators": f"https://{server}/c/{actor}/moderators",
                "featured": f"https://{server}/c/{actor}/featured",
                "attributedTo": f"https://{server}/c/{actor}/moderators",
                "postingRestrictedToMods": community.restricted_to_mods,
                "url": f"https://{server}/c/{actor}",
                "publicKey": {
                    "id": f"https://{server}/c/{actor}#main-key",
                    "owner": f"https://{server}/c/{actor}",
                    "publicKeyPem": community.public_key
                },
                "endpoints": {
                    "sharedInbox": f"https://{server}/inbox"
                },
                "published": community.created_at.isoformat() + '+00:00',
                "updated": community.last_active.isoformat() + '+00:00',
            }
            if community.icon_id is not None:
                actor_data["icon"] = {
                    "type": "Image",
                    "url": f"https://{server}/avatars/{community.icon.file_path}"
                }
            resp = jsonify(actor_data)
            resp.content_type = 'application/activity+json'
            return resp
        else:   # browser request - return html
            return show_community(community)
    else:
        abort(404)


@bp.route('/inbox', methods=['GET', 'POST'])
def shared_inbox():
    if request.method == 'POST':
        # save all incoming data to aid in debugging and development
        activity_log = ActivityPubLog(direction='in', activity_json=request.data, result='failure')

        try:
            request_json = request.get_json(force=True)
        except werkzeug.exceptions.BadRequest as e:
            activity_log.exception_message = 'Unable to parse json body: ' + e.description
            activity_log.result = 'failure'
            db.session.add(activity_log)
            db.session.commit()
            return
        else:
            if 'id' in request_json:
                activity_log.activity_id = request_json['id']

        actor = find_actor_or_create(request_json['actor']) if 'actor' in request_json else None
        if actor is not None:
            if HttpSignature.verify_request(request, actor.public_key, skip_date=True):
                if 'type' in request_json:
                    activity_log.activity_type = request_json['type']
                    if not instance_blocked(request_json['id']):
                        # Create is new content
                        if request_json['type'] == 'Create':
                            activity_log.activity_type = 'Create'
                            user_ap_id = request_json['object']['attributedTo']
                            community_ap_id = request_json['to'][0]
                            if community_ap_id == 'https://www.w3.org/ns/activitystreams#Public':   # kbin does this when posting a reply
                                if 'to' in request_json['object'] and request_json['object']['to']:
                                    community_ap_id = request_json['object']['to'][0]
                                    if community_ap_id == 'https://www.w3.org/ns/activitystreams#Public' and 'cc' in request_json['object'] and request_json['object']['cc']:
                                        community_ap_id = request_json['object']['cc'][0]
                                elif 'cc' in request_json['object'] and request_json['object']['cc']:
                                    community_ap_id = request_json['object']['cc'][0]
                            community = find_actor_or_create(community_ap_id)
                            user = find_actor_or_create(user_ap_id)
                            if user and community:
                                object_type = request_json['object']['type']
                                new_content_types = ['Page', 'Article', 'Link', 'Note']
                                if object_type in new_content_types:  # create a new post
                                    in_reply_to = request_json['object']['inReplyTo'] if 'inReplyTo' in \
                                                                                                   request_json[
                                                                                                       'object'] else None
                                    if not in_reply_to:
                                        post = Post(user_id=user.id, community_id=community.id,
                                                    title=request_json['object']['name'],
                                                    comments_enabled=request_json['object'][
                                                        'commentsEnabled'],
                                                    sticky=request_json['object']['stickied'] if 'stickied' in
                                                                                                           request_json[
                                                                                                               'object'] else False,
                                                    nsfw=request_json['object']['sensitive'],
                                                    nsfl=request_json['object']['nsfl'] if 'nsfl' in request_json[
                                                                                                         'object'] else False,
                                                    ap_id=request_json['object']['id'],
                                                    ap_create_id=request_json['id'],
                                                    ap_announce_id=None,
                                                    type=constants.POST_TYPE_ARTICLE,
                                                    up_votes=1,
                                                    score=instance_weight(user.ap_domain)
                                                    )
                                        if 'source' in request_json['object'] and \
                                                request_json['object']['source'][
                                                    'mediaType'] == 'text/markdown':
                                            post.body = request_json['object']['source']['content']
                                            post.body_html = markdown_to_html(post.body)
                                        elif 'content' in request_json['object'] and request_json['object']['content'] is not None:
                                            post.body_html = allowlist_html(request_json['object']['content'])
                                            post.body = html_to_markdown(post.body_html)
                                        if 'attachment' in request_json['object'] and \
                                                len(request_json['object']['attachment']) > 0 and \
                                                'type' in request_json['object']['attachment'][0]:
                                            if request_json['object']['attachment'][0]['type'] == 'Link':
                                                post.url = request_json['object']['attachment'][0]['href']
                                                if is_image_url(post.url):
                                                    post.type = POST_TYPE_IMAGE
                                                else:
                                                    post.type = POST_TYPE_LINK
                                                domain = domain_from_url(post.url)
                                                if not domain.banned:
                                                    post.domain_id = domain.id
                                                else:
                                                    post = None
                                                    activity_log.exception_message = domain.name + ' is blocked by admin'
                                                    activity_log.result = 'failure'
                                        if 'image' in request_json['object']:
                                            image = File(source_url=request_json['object']['image']['url'])
                                            db.session.add(image)
                                            post.image = image

                                        if post is not None:
                                            db.session.add(post)
                                            community.post_count += 1
                                            community.last_active = datetime.utcnow()
                                            activity_log.result = 'success'
                                            db.session.commit()
                                            vote = PostVote(user_id=user.id, author_id=post.user_id,
                                                                 post_id=post.id,
                                                                 effect=instance_weight(user.ap_domain))
                                            db.session.add(vote)
                                    else:
                                        post_id, parent_comment_id, root_id = find_reply_parent(in_reply_to)
                                        post_reply = PostReply(user_id=user.id, community_id=community.id,
                                                               post_id=post_id, parent_id=parent_comment_id,
                                                               root_id=root_id,
                                                               nsfw=community.nsfw,
                                                               nsfl=community.nsfl,
                                                               up_votes=1,
                                                               score=instance_weight(user.ap_domain),
                                                               ap_id=request_json['object']['id'],
                                                               ap_create_id=request_json['id'],
                                                               ap_announce_id=None)
                                        if 'source' in request_json['object'] and \
                                                request_json['object']['source'][
                                                    'mediaType'] == 'text/markdown':
                                            post_reply.body = request_json['object']['source']['content']
                                            post_reply.body_html = markdown_to_html(post_reply.body)
                                        elif 'content' in request_json['object']:
                                            post_reply.body_html = allowlist_html(
                                                request_json['object']['content'])
                                            post_reply.body = html_to_markdown(post_reply.body_html)

                                        if post_reply is not None:
                                            post = Post.query.get(post_id)
                                            db.session.add(post_reply)
                                            post.reply_count += 1
                                            community.post_reply_count += 1
                                            community.last_active = datetime.utcnow()
                                            activity_log.result = 'success'
                                            db.session.commit()
                                            vote = PostReplyVote(user_id=user.id, author_id=post_reply.user_id, post_reply_id=post_reply.id,
                                                                effect=instance_weight(user.ap_domain))
                                            db.session.add(vote)
                                else:
                                    activity_log.exception_message = 'Unacceptable type (kbin): ' + object_type

                        # Announce is new content and votes, mastodon style (?)
                        if request_json['type'] == 'Announce':
                            if request_json['object']['type'] == 'Create':
                                activity_log.activity_type = request_json['object']['type']
                                user_ap_id = request_json['object']['object']['attributedTo']
                                community_ap_id = request_json['object']['audience']
                                community = find_actor_or_create(community_ap_id)
                                user = find_actor_or_create(user_ap_id)
                                if user and community:
                                    object_type = request_json['object']['object']['type']
                                    new_content_types = ['Page', 'Article', 'Link', 'Note']
                                    if object_type in new_content_types:      # create a new post
                                        in_reply_to = request_json['object']['object']['inReplyTo'] if 'inReplyTo' in \
                                                                                                       request_json['object']['object'] else None

                                        if not in_reply_to:
                                            post = Post(user_id=user.id, community_id=community.id,
                                                        title=request_json['object']['object']['name'],
                                                        comments_enabled=request_json['object']['object']['commentsEnabled'],
                                                        sticky=request_json['object']['object']['stickied'] if 'stickied' in request_json['object']['object'] else False,
                                                        nsfw=request_json['object']['object']['sensitive'],
                                                        nsfl=request_json['object']['object']['nsfl'] if 'nsfl' in request_json['object']['object'] else False,
                                                        ap_id=request_json['object']['object']['id'],
                                                        ap_create_id=request_json['object']['id'],
                                                        ap_announce_id=request_json['id'],
                                                        type=constants.POST_TYPE_ARTICLE
                                                        )
                                            if 'source' in request_json['object']['object'] and \
                                                    request_json['object']['object']['source']['mediaType'] == 'text/markdown':
                                                post.body = request_json['object']['object']['source']['content']
                                                post.body_html = markdown_to_html(post.body)
                                            elif 'content' in request_json['object']['object']:
                                                post.body_html = allowlist_html(request_json['object']['object']['content'])
                                                post.body = html_to_markdown(post.body_html)
                                            if 'attachment' in request_json['object']['object'] and \
                                                    len(request_json['object']['object']['attachment']) > 0 and \
                                                    'type' in request_json['object']['object']['attachment'][0]:
                                                if request_json['object']['object']['attachment'][0]['type'] == 'Link':
                                                    post.url = request_json['object']['object']['attachment'][0]['href']
                                                    if is_image_url(post.url):
                                                        post.type = POST_TYPE_IMAGE
                                                    else:
                                                        post.type = POST_TYPE_LINK
                                                    domain = domain_from_url(post.url)
                                                    if not domain.banned:
                                                        post.domain_id = domain.id
                                                    else:
                                                        post = None
                                                        activity_log.exception_message = domain.name + ' is blocked by admin'
                                                        activity_log.result = 'failure'
                                            if 'image' in request_json['object']['object']:
                                                image = File(source_url=request_json['object']['object']['image']['url'])
                                                db.session.add(image)
                                                post.image = image

                                            if post is not None:
                                                db.session.add(post)
                                                community.post_count += 1
                                                db.session.commit()
                                        else:
                                            post_id, parent_comment_id, root_id = find_reply_parent(in_reply_to)
                                            post_reply = PostReply(user_id=user.id, community_id=community.id,
                                                                   post_id=post_id, parent_id=parent_comment_id,
                                                                   root_id=root_id,
                                                                   nsfw=community.nsfw,
                                                                   nsfl=community.nsfl,
                                                                   ap_id=request_json['object']['object']['id'],
                                                                   ap_create_id=request_json['object']['id'],
                                                                   ap_announce_id=request_json['id'])
                                            if 'source' in request_json['object']['object'] and \
                                                    request_json['object']['object']['source'][
                                                        'mediaType'] == 'text/markdown':
                                                post_reply.body = request_json['object']['object']['source']['content']
                                                post_reply.body_html = markdown_to_html(post_reply.body)
                                            elif 'content' in request_json['object']['object']:
                                                post_reply.body_html = allowlist_html(
                                                    request_json['object']['object']['content'])
                                                post_reply.body = html_to_markdown(post_reply.body_html)

                                            if post_reply is not None:
                                                db.session.add(post_reply)
                                                community.post_reply_count += 1
                                                db.session.commit()
                                    else:
                                        activity_log.exception_message = 'Unacceptable type: ' + object_type

                            elif request_json['object']['type'] == 'Like' or request_json['object']['type'] == 'Dislike':
                                activity_log.activity_type = request_json['object']['type']
                                vote_effect = 1.0 if request_json['object']['type'] == 'Like' else -1.0
                                if vote_effect < 0 and get_setting('allow_dislike', True) is False:
                                    activity_log.exception_message = 'Dislike ignored because of allow_dislike setting'
                                else:
                                    user_ap_id = request_json['object']['actor']
                                    liked_ap_id = request_json['object']['object']
                                    user = find_actor_or_create(user_ap_id)
                                    if user:
                                        vote_weight = instance_weight(user.ap_domain)
                                        liked = find_liked_object(liked_ap_id)
                                        # insert into voted table
                                        if liked is None:
                                            activity_log.exception_message = 'Liked object not found'
                                        elif liked is not None and isinstance(liked, Post):
                                            existing_vote = PostVote.query.filter_by(user_id=user.id, post_id=liked.id).first()
                                            if existing_vote:
                                                existing_vote.effect = vote_effect * vote_weight
                                            else:
                                                vote = PostVote(user_id=user.id, author_id=liked.user_id, post_id=liked.id,
                                                                effect=vote_effect * vote_weight)
                                                db.session.add(vote)
                                            db.session.commit()
                                            activity_log.result = 'success'
                                        elif liked is not None and isinstance(liked, PostReply):
                                            existing_vote = PostVote.query.filter_by(user_id=user.id, post_id=liked.id).first()
                                            if existing_vote:
                                                existing_vote.effect = vote_effect * vote_weight
                                            else:
                                                vote = PostReplyVote(user_id=user.id, author_id=liked.user_id, post_reply_id=liked.id,
                                                                effect=vote_effect * vote_weight)
                                                db.session.add(vote)
                                            db.session.commit()
                                            activity_log.result = 'success'
                                        else:
                                            activity_log.exception_message = 'Could not detect type of like'
                                        if activity_log.result == 'success':
                                            ... # todo: recalculate 'hotness' of liked post/reply
                                                # todo: if vote was on content in local community, federate the vote out to followers

                        # Follow: remote user wants to join/follow one of our communities
                        elif request_json['type'] == 'Follow':      # Follow is when someone wants to join a community
                            user_ap_id = request_json['actor']
                            community_ap_id = request_json['object']
                            follow_id = request_json['id']
                            user = find_actor_or_create(user_ap_id)
                            community = find_actor_or_create(community_ap_id)
                            if user is not None and community is not None:
                                # check if user is banned from this community
                                banned = CommunityBan.query.filter_by(user_id=user.id,
                                                                      community_id=community.id).first()
                                if banned is None:
                                    if community_membership(user, community) != SUBSCRIPTION_MEMBER:
                                        member = CommunityMember(user_id=user.id, community_id=community.id)
                                        db.session.add(member)
                                        db.session.commit()
                                        cache.delete_memoized(community_membership, user, community)
                                    # send accept message to acknowledge the follow
                                    accept = {
                                        "@context": default_context(),
                                        "actor": community.ap_profile_id,
                                        "to": [
                                            user.ap_profile_id
                                        ],
                                        "object": {
                                            "actor": user.ap_profile_id,
                                            "to": None,
                                            "object": community.ap_profile_id,
                                            "type": "Follow",
                                            "id": follow_id
                                        },
                                        "type": "Accept",
                                        "id": f"https://{current_app.config['SERVER_NAME']}/activities/accept/" + gibberish(32)
                                    }
                                    try:
                                        HttpSignature.signed_request(user.ap_inbox_url, accept, community.private_key,
                                                                     f"https://{current_app.config['SERVER_NAME']}/c/{community.name}#main-key")
                                    except Exception as e:
                                        accept_log = ActivityPubLog(direction='out', activity_json=json.dumps(accept),
                                                                    result='failure', activity_id=accept['id'],
                                                                    exception_message = 'could not send Accept' + str(e))
                                        db.session.add(accept_log)
                                        db.session.commit()
                                        return
                                    activity_log.result = 'success'
                                else:
                                    activity_log.exception_message = 'user is banned from this community'
                        # Accept: remote server is accepting our previous follow request
                        elif request_json['type'] == 'Accept':
                            if request_json['object']['type'] == 'Follow':
                                community_ap_id = request_json['actor']
                                user_ap_id = request_json['object']['actor']
                                user = find_actor_or_create(user_ap_id)
                                community = find_actor_or_create(community_ap_id)
                                if user and community:
                                    join_request = CommunityJoinRequest.query.filter_by(user_id=user.id,
                                                                                        community_id=community.id).first()
                                    if join_request:
                                        member = CommunityMember(user_id=user.id, community_id=community.id)
                                        db.session.add(member)
                                        community.subscriptions_count += 1
                                        db.session.commit()
                                        activity_log.result = 'success'
                                        cache.delete_memoized(community_membership, user, community)

                        elif request_json['type'] == 'Undo':
                            if request_json['object']['type'] == 'Follow':  # Unsubscribe from a community
                                community_ap_id = request_json['object']['object']
                                user_ap_id = request_json['object']['actor']
                                user = find_actor_or_create(user_ap_id)
                                community = find_actor_or_create(community_ap_id)
                                if user and community:
                                    member = CommunityMember.query.filter_by(user_id=user.id, community_id=community.id).first()
                                    join_request = CommunityJoinRequest.query.filter_by(user_id=user.id,
                                                                                        community_id=community.id).first()
                                    if member:
                                        db.session.delete(member)
                                    if join_request:
                                        db.session.delete(join_request)
                                    db.session.commit()
                                    activity_log.result = 'success'
                            elif request_json['object']['type'] == 'Like':  # Undoing an upvote or downvote
                                activity_log.activity_type = request_json['object']['type']
                                user_ap_id = request_json['actor']
                                user = find_actor_or_create(user_ap_id)
                                post = None
                                comment = None
                                target_ap_id = request_json['object']['object']
                                if '/comment/' in target_ap_id:
                                    comment = PostReply.query.filter_by(ap_id=target_ap_id).first()
                                if '/post/' in target_ap_id:
                                    post = Post.query.filter_by(ap_id=target_ap_id).first()
                                if user and post:
                                    existing_vote = PostVote.query.filter_by(user_id=user.id, post_id=post.id).first()
                                    if existing_vote:
                                        post.author.reputation -= existing_vote.effect
                                        if existing_vote.effect < 0:    # Lemmy sends 'like' for upvote and 'dislike' for down votes. Cool! When it undoes an upvote it sends an 'Undo Like'. Fine. When it undoes a downvote it sends an 'Undo Like' - not 'Undo Dislike'?!
                                            post.down_votes -= 1
                                        else:
                                            post.up_votes -= 1
                                        post.score -= existing_vote.effect
                                        db.session.delete(existing_vote)
                                        activity_log.result = 'success'
                                if user and comment:
                                    existing_vote = PostReplyVote.query.filter_by(user_id=user.id, post_reply_id=comment.id).first()
                                    if existing_vote:
                                        comment.author.reputation -= existing_vote.effect
                                        if existing_vote.effect < 0:  # Lemmy sends 'like' for upvote and 'dislike' for down votes. Cool! When it undoes an upvote it sends an 'Undo Like'. Fine. When it undoes a downvote it sends an 'Undo Like' - not 'Undo Dislike'?!
                                            comment.down_votes -= 1
                                        else:
                                            comment.up_votes -= 1
                                        comment.score -= existing_vote.effect
                                        db.session.delete(existing_vote)
                                        activity_log.result = 'success'

                            elif request_json['object']['type'] == 'Dislike':  # Undoing a downvote - probably unused
                                activity_log.activity_type = request_json['object']['type']
                                user_ap_id = request_json['actor']
                                user = find_actor_or_create(user_ap_id)
                                post = None
                                comment = None
                                target_ap_id = request_json['object']['object']
                                if '/comment/' in target_ap_id:
                                    comment = PostReply.query.filter_by(ap_id=target_ap_id).first()
                                if '/post/' in target_ap_id:
                                    post = Post.query.filter_by(ap_id=target_ap_id).first()
                                if user and post:
                                    existing_vote = PostVote.query.filter_by(user_id=user.id, post_id=post.id).first()
                                    if existing_vote:
                                        post.author.reputation -= existing_vote.effect
                                        post.down_votes -= 1
                                        post.score -= existing_vote.effect
                                        db.session.delete(existing_vote)
                                        activity_log.result = 'success'
                                if user and comment:
                                    existing_vote = PostReplyVote.query.filter_by(user_id=user.id,
                                                                                  post_reply_id=comment.id).first()
                                    if existing_vote:
                                        comment.author.reputation -= existing_vote.effect
                                        comment.down_votes -= 1
                                        comment.score -= existing_vote.effect
                                        db.session.delete(existing_vote)
                                        activity_log.result = 'success'

                        elif request_json['type'] == 'Update':
                            if request_json['object']['type'] == 'Page':    # Editing a post
                                post = Post.query.filter_by(ap_id=request_json['object']['id']).first()
                                if post:
                                    if 'source' in request_json['object'] and \
                                            request_json['object']['source']['mediaType'] == 'text/markdown':
                                        post.body = request_json['object']['source']['content']
                                        post.body_html = markdown_to_html(post.body)
                                    elif 'content' in request_json['object']:
                                        post.body_html = allowlist_html(request_json['object']['content'])
                                        post.body = html_to_markdown(post.body_html)
                                    post.edited_at = datetime.utcnow()
                                    db.session.commit()
                                    activity_log.result = 'success'
                            elif request_json['object']['type'] == 'Note':  # Editing a reply
                                reply = PostReply.query.filter_by(ap_id=request_json['object']['id']).first()
                                if reply:
                                    if 'source' in request_json['object'] and \
                                            request_json['object']['source']['mediaType'] == 'text/markdown':
                                        reply.body = request_json['object']['source']['content']
                                        reply.body_html = markdown_to_html(reply.body)
                                    elif 'content' in request_json['object']:
                                        reply.body_html = allowlist_html(request_json['object']['content'])
                                        reply.body = html_to_markdown(reply.body_html)
                                    reply.edited_at = datetime.utcnow()
                                    db.session.commit()
                                    activity_log.result = 'success'
                        elif request_json['type'] == 'Delete':
                            if isinstance(request_json['object'], str):
                                ap_id = request_json['object']          # lemmy
                            else:
                                ap_id = request_json['object']['id']    # kbin
                            post = Post.query.filter_by(ap_id=ap_id).first()
                            if post:
                                post.delete_dependencies()
                                db.session.delete(post)
                            else:
                                reply = PostReply.query.filter_by(ap_id=ap_id).first()
                                if reply:
                                    reply.body_html = '<p><em>deleted</em></p>'
                                    reply.body = 'deleted'
                            db.session.commit()
                            activity_log.result = 'success'
                        elif request_json['type'] == 'Like':                    # Upvote
                            activity_log.activity_type = request_json['type']
                            user_ap_id = request_json['actor']
                            user = find_actor_or_create(user_ap_id)
                            target_ap_id = request_json['object']
                            post = None
                            comment = None
                            effect = instance_weight(user.ap_domain)
                            if '/comment/' in target_ap_id:
                                comment = PostReply.query.filter_by(ap_id=target_ap_id).first()
                            if '/post/' in target_ap_id:
                                post = Post.query.filter_by(ap_id=target_ap_id).first()
                            if user and post:
                                existing_vote = PostVote.query.filter_by(user_id=user.id, post_id=post.id).first()
                                if not existing_vote:
                                    post.up_votes += 1
                                    post.score += effect
                                    vote = PostVote(user_id=user.id, post_id=post.id, author_id=post.author.id,
                                                    effect=effect)
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
                                        post.author.reputation += effect
                                        db.session.add(vote)
                                activity_log.result = 'success'
                            elif user and comment:
                                existing_vote = PostReplyVote.query.filter_by(user_id=user.id,
                                                                              post_reply_id=comment.id).first()
                                if not existing_vote:
                                    comment.up_votes += 1
                                    comment.score += effect
                                    vote = PostReplyVote(user_id=user.id, post_reply_id=comment.id,
                                                         author_id=comment.author.id, effect=effect)
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
                                        comment.author.reputation += effect
                                        db.session.add(vote)
                                    else:
                                        pass    # they have already upvoted this reply
                                activity_log.result = 'success'

                        elif request_json['type'] == 'Dislike':                 # Downvote
                            if get_setting('allow_dislike', True) is False:
                                activity_log.exception_message = 'Dislike ignored because of allow_dislike setting'
                            else:
                                activity_log.activity_type = request_json['type']
                                user_ap_id = request_json['actor']
                                user = find_actor_or_create(user_ap_id)
                                target_ap_id = request_json['object']
                                post = None
                                comment = None
                                if '/comment/' in target_ap_id:
                                    comment = PostReply.query.filter_by(ap_id=target_ap_id).first()
                                if '/post/' in target_ap_id:
                                    post = Post.query.filter_by(ap_id=target_ap_id).first()
                                if user and comment:
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
                                            pass    # they have already downvoted this reply
                                    activity_log.result = 'success'
                                elif user and post:
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
                                    activity_log.result = 'success'
                                else:
                                    activity_log.exception_message = 'Could not find user or content for vote'
                    else:
                        activity_log.exception_message = 'Instance banned'
            else:
                activity_log.exception_message = 'Could not verify signature'
        else:
            activity_log.exception_message = 'Actor could not be found: ' + request_json['actor']

        if activity_log.exception_message is not None:
            activity_log.result = 'failure'
        db.session.add(activity_log)
        db.session.commit()
        return ''


@bp.route('/c/<actor>/outbox', methods=['GET'])
def community_outbox(actor):
    actor = actor.strip()
    community = Community.query.filter_by(name=actor, banned=False, ap_id=None).first()
    if community is not None:
        posts = community.posts.limit(50).all()

        community_data = {
            "@context": default_context(),
            "type": "OrderedCollection",
            "id": f"https://{current_app.config['SERVER_NAME']}/c/{actor}/outbox",
            "totalItems": len(posts),
            "orderedItems": []
        }

        for post in posts:
            community_data['orderedItems'].append(post_to_activity(post, community))

        return jsonify(community_data)


@bp.route('/c/<actor>/moderators', methods=['GET'])
def community_moderators(actor):
    actor = actor.strip()
    community = Community.query.filter_by(name=actor, banned=False, ap_id=None).first()
    if community is not None:
        moderator_ids = community.moderators()
        moderators = User.query.filter(User.id.in_([mod.user_id for mod in moderator_ids])).all()
        community_data = {
            "@context": default_context(),
            "type": "OrderedCollection",
            "id": f"https://{current_app.config['SERVER_NAME']}/c/{actor}/moderators",
            "totalItems": len(moderators),
            "orderedItems": []
        }

        for moderator in moderators:
            community_data['orderedItems'].append(moderator.ap_profile_id)

        return jsonify(community_data)


@bp.route('/inspect')
def inspect():
    return Response(b'<br><br>'.join(INBOX), status=200)


@bp.route('/users/<actor>/inbox', methods=['GET', 'POST'])
def inbox(actor):
    """ To post to this inbox, you could use curl:
    $ curl -d '{"key" : "value"}' -H "Content-Type: application/json" -X POST http://localhost:5001/users/test/inbox
    Or, with an actual Mastodon follow request:
    $ curl -d '{"@context":["https://www.w3.org/ns/activitystreams","https://w3id.org/security/v1",{"manuallyApprovesFollowers":"as:manuallyApprovesFollowers","sensitive":"as:sensitive","movedTo":{"@id":"as:movedTo","@type":"@id"},"Hashtag":"as:Hashtag","ostatus":"http://ostatus.org#","atomUri":"ostatus:atomUri","inReplyToAtomUri":"ostatus:inReplyToAtomUri","conversation":"ostatus:conversation","toot":"http://joinmastodon.org/ns#","Emoji":"toot:Emoji","focalPoint":{"@container":"@list","@id":"toot:focalPoint"},"featured":{"@id":"toot:featured","@type":"@id"},"schema":"http://schema.org#","PropertyValue":"schema:PropertyValue","value":"schema:value"}],"id":"https://post.lurk.org/02d04ed5-dda6-48f3-a551-2e9c554de745","type":"Follow","actor":"https://post.lurk.org/users/manetta","object":"https://ap.virtualprivateserver.space/users/test","signature":{"type":"RsaSignature2017","creator":"https://post.lurk.org/users/manetta#main-key","created":"2018-11-28T16:15:35Z","signatureValue":"XUdBg+Zj9pkdOXlAYHhOtZlmU1Jdt63zwh2cXoJ8E8C1C+KvgGilkyfPTud9VNymVwdUQRl+YEW9KAZiiGaHb9H+tdVUr9BEkuR5E/tGehbMZr1sakC+qPehe4s3bRKEpJjTTJnTiSHaW7V6Qvr1u6+MVts6oj32az/ixuB/CfodSr3K/K+jZmmOl6SIUqX7Xg7xGwOxIsYaR7g9wbcJ4qyzKcTPZonPMsONq9/RSm3SeQBo7WO1FKlQiFxVP/y5eFaFP8GYDLZyK7Nj5kDL5TannfEpuF8f3oyTBErQhcFQYKcBZNbuaqX/WiIaGjtHIL2ctJe0Psb5Nfshx4MXmQ=="}}' -H "Content-Type: application/json" -X POST http://localhost:5001/users/test/inbox
    """

    if request.method == 'GET':
        return '''This has been a <em>{}</em> request. <br>
        It came with the following header: <br><br><em>{}</em><br><br>
        You have searched for the actor <em>{}</em>. <br>
        This is <em>{}</em>'s shared inbox: <br><br><em>{}</em>'''.format(request.method, request.headers, actor,
                                                                          current_app.config['SERVER_NAME'], str(INBOX))

    if request.method == 'POST':
        INBOX.append(request.data)
        return Response(status=200)
