from app import db, constants, cache, celery
from app.activitypub import bp
from flask import request, Response, current_app, abort, jsonify, json, g

from app.activitypub.signature import HttpSignature
from app.community.routes import show_community
from app.post.routes import continue_discussion, show_post
from app.user.routes import show_profile
from app.constants import POST_TYPE_LINK, POST_TYPE_IMAGE, SUBSCRIPTION_MEMBER
from app.models import User, Community, CommunityJoinRequest, CommunityMember, CommunityBan, ActivityPubLog, Post, \
    PostReply, Instance, PostVote, PostReplyVote, File, AllowedInstances, BannedInstances, utcnow, Site
from app.activitypub.util import public_key, users_total, active_half_year, active_month, local_posts, local_comments, \
    post_to_activity, find_actor_or_create, default_context, instance_blocked, find_reply_parent, find_liked_object, \
    lemmy_site_data, instance_weight, is_activitypub_request, downvote_post_reply, downvote_post, upvote_post_reply, \
    upvote_post, activity_already_ingested, make_image_sizes, delete_post_or_comment, community_members
from app.utils import gibberish, get_setting, is_image_url, allowlist_html, html_to_markdown, render_template, \
    domain_from_url, markdown_to_html, community_membership, ap_datetime, markdown_to_text
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
@cache.cached(timeout=600)
def nodeinfo():
    nodeinfo_data = {"links": [{"rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
                                "href": f"https://{current_app.config['SERVER_NAME']}/nodeinfo/2.0"}]}
    return jsonify(nodeinfo_data)


@bp.route('/nodeinfo/2.0')
@bp.route('/nodeinfo/2.0.json')
@cache.cached(timeout=600)
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
                "openRegistrations": g.site.registration_mode == 'Open'
            }
    return jsonify(nodeinfo_data)


@bp.route('/api/v3/site')
@cache.cached(timeout=600)
def lemmy_site():
    return jsonify(lemmy_site_data())


@bp.route('/api/v3/federated_instances')
@cache.cached(timeout=600)
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
        allowed.append({"id": instance.id, "domain": instance.domain, "published": utcnow(), "updated": utcnow()})
    for instance in BannedInstances.query.all():
        blocked.append({"id": instance.id, "domain": instance.domain, "published": utcnow(), "updated": utcnow()})
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
        if is_activitypub_request():
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
                            "published": ap_datetime(user.created),
                        }
            if user.avatar_id is not None:
                actor_data["icon"] = {
                    "type": "Image",
                    "url": f"https://{current_app.config['SERVER_NAME']}{user.avatar_image()}"
                }
            if user.cover_id is not None:
                actor_data["image"] = {
                    "type": "Image",
                    "url": f"https://{current_app.config['SERVER_NAME']}{user.cover_image()}"
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


@bp.route('/u/<actor>/outbox', methods=['GET'])
def user_outbox(actor):
    outbox = {
        "@context": default_context(),
        'type': 'OrderedCollection',
        'id': f"https://{current_app.config['SERVER_NAME']}/u/{actor}/outbox",
        'orderedItems': [],
        'totalItems': 0
    }
    resp = jsonify(outbox)
    resp.content_type = 'application/activity+json'
    return resp


@bp.route('/c/<actor>', methods=['GET'])
def community_profile(actor):
    """ Requests to this endpoint can be for a JSON representation of the community, or a HTML rendering of it.
        The two types of requests are differentiated by the header """
    actor = actor.strip()
    if '@' in actor:
        # don't provide activitypub info for remote communities
        if 'application/ld+json' in request.headers.get('Accept', '') or 'application/activity+json' in request.headers.get('Accept', ''):
            abort(400)
        community: Community = Community.query.filter_by(ap_id=actor, banned=False).first()
    else:
        community: Community = Community.query.filter_by(name=actor, banned=False, ap_id=None).first()
    if community is not None:
        if is_activitypub_request():
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
                "published": ap_datetime(community.created_at),
                "updated": ap_datetime(community.last_active),
            }
            if community.icon_id is not None:
                actor_data["icon"] = {
                    "type": "Image",
                    "url": f"https://{current_app.config['SERVER_NAME']}{community.icon_image()}"
                }
            if community.image_id is not None:
                actor_data["image"] = {
                    "type": "Image",
                    "url": f"https://{current_app.config['SERVER_NAME']}{community.header_image()}"
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
        # save all incoming data to aid in debugging and development. Set result to 'success' if things go well
        activity_log = ActivityPubLog(direction='in', activity_json=request.data, result='failure')

        try:
            request_json = request.get_json(force=True)
        except werkzeug.exceptions.BadRequest as e:
            activity_log.exception_message = 'Unable to parse json body: ' + e.description
            activity_log.result = 'failure'
            db.session.add(activity_log)
            db.session.commit()
            return ''

        if 'id' in request_json:
            if activity_already_ingested(request_json['id']):   # Lemmy has an extremely short POST timeout and tends to retry unnecessarily. Ignore their retries.
                activity_log.result = 'ignored'
                db.session.add(activity_log)
                db.session.commit()
                return ''

            activity_log.activity_id = request_json['id']
            activity_log.activity_json = json.dumps(request_json)
            activity_log.result = 'processing'

            # Mastodon spams the whole fediverse whenever any of their users are deleted. Ignore them, for now. The Activity includes the Actor signature so it should be possible to verify the POST and do the delete if valid, without a call to find_actor_or_create() and all the network activity that involves. One day.
            if 'type' in request_json and request_json['type'] == 'Delete' and request_json['id'].endswith('#delete'):
                activity_log.result = 'ignored'
                activity_log.activity_type = 'Delete'
                db.session.add(activity_log)
                db.session.commit()
                return ''
            else:
                db.session.add(activity_log)
                db.session.commit()
        else:
            activity_log.activity_id = ''
            activity_log.activity_json = json.dumps(request_json)
            db.session.add(activity_log)
            db.session.commit()

        actor = find_actor_or_create(request_json['actor']) if 'actor' in request_json else None
        if actor is not None:
            if HttpSignature.verify_request(request, actor.public_key, skip_date=True):
                if current_app.debug:
                    process_inbox_request(request_json, activity_log.id)
                else:
                    process_inbox_request.delay(request_json, activity_log.id)
                return ''
            else:
                activity_log.exception_message = 'Could not verify signature'
        else:
            actor_name = request_json['actor'] if 'actor' in request_json else ''
            activity_log.exception_message = f'Actor could not be found: {actor_name}'

        if activity_log.exception_message is not None:
            activity_log.result = 'failure'
        db.session.commit()
    return ''


@celery.task
def process_inbox_request(request_json, activitypublog_id):
    with current_app.app_context():
        activity_log = ActivityPubLog.query.get(activitypublog_id)
        site = Site.query.get(1)    # can't use g.site because celery doesn't use Flask's g variable
        if 'type' in request_json:
            activity_log.activity_type = request_json['type']
            if not instance_blocked(request_json['id']):
                # Create is new content
                if request_json['type'] == 'Create':
                    activity_log.activity_type = 'Create'
                    user_ap_id = request_json['object']['attributedTo']
                    community_ap_id = request_json['to'][0]
                    if community_ap_id == 'https://www.w3.org/ns/activitystreams#Public':  # kbin does this when posting a reply
                        if 'to' in request_json['object'] and request_json['object']['to']:
                            community_ap_id = request_json['object']['to'][0]
                            if community_ap_id == 'https://www.w3.org/ns/activitystreams#Public' and 'cc' in \
                                    request_json['object'] and request_json['object']['cc']:
                                community_ap_id = request_json['object']['cc'][0]
                        elif 'cc' in request_json['object'] and request_json['object']['cc']:
                            community_ap_id = request_json['object']['cc'][0]
                        if community_ap_id.endswith('/followers'):  # mastodon
                            if 'inReplyTo' in request_json['object']:
                                post_being_replied_to = Post.query.filter_by(ap_id=request_json['object']['inReplyTo']).first()
                                if post_being_replied_to:
                                    community_ap_id = post_being_replied_to.community.ap_profile_id
                    community = find_actor_or_create(community_ap_id)
                    user = find_actor_or_create(user_ap_id)
                    if (user and not user.is_local()) and community:
                        user.last_seen = community.last_active = site.last_active = utcnow()

                        object_type = request_json['object']['type']
                        new_content_types = ['Page', 'Article', 'Link', 'Note']
                        if object_type in new_content_types:  # create a new post
                            in_reply_to = request_json['object']['inReplyTo'] if 'inReplyTo' in request_json['object'] else None
                            if not in_reply_to:
                                post = Post(user_id=user.id, community_id=community.id,
                                            title=request_json['object']['name'],
                                            comments_enabled=request_json['object']['commentsEnabled'],
                                            sticky=request_json['object']['stickied'] if 'stickied' in request_json['object'] else False,
                                            nsfw=request_json['object']['sensitive'],
                                            nsfl=request_json['object']['nsfl'] if 'nsfl' in request_json['object'] else False,
                                            ap_id=request_json['object']['id'],
                                            ap_create_id=request_json['id'],
                                            ap_announce_id=None,
                                            type=constants.POST_TYPE_ARTICLE,
                                            up_votes=1,
                                            score=instance_weight(user.ap_domain)
                                            )
                                if 'source' in request_json['object'] and request_json['object']['source']['mediaType'] == 'text/markdown':
                                    post.body = request_json['object']['source']['content']
                                    post.body_html = markdown_to_html(post.body)
                                elif 'content' in request_json['object'] and request_json['object']['content'] is not None:
                                    post.body_html = allowlist_html(request_json['object']['content'])
                                    post.body = html_to_markdown(post.body_html)
                                if 'attachment' in request_json['object'] and len(request_json['object']['attachment']) > 0 and \
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
                                if 'image' in request_json['object']:
                                    image = File(source_url=request_json['object']['image']['url'])
                                    db.session.add(image)
                                    post.image = image

                                if post is not None:
                                    db.session.add(post)
                                    community.post_count += 1
                                    community.last_active = utcnow()
                                    activity_log.result = 'success'
                                    db.session.commit()

                                    if post.image_id:
                                        make_image_sizes(post.image_id, 266, None, 'posts')

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
                                                       ap_announce_id=None,
                                                       instance_id=user.instance_id)
                                if 'source' in request_json['object'] and \
                                        request_json['object']['source']['mediaType'] == 'text/markdown':
                                    post_reply.body = request_json['object']['source']['content']
                                    post_reply.body_html = markdown_to_html(post_reply.body)
                                elif 'content' in request_json['object']:
                                    post_reply.body_html = allowlist_html(request_json['object']['content'])
                                    post_reply.body = html_to_markdown(post_reply.body_html)

                                if post_reply is not None:
                                    post = Post.query.get(post_id)
                                    if post.comments_enabled:
                                        db.session.add(post_reply)
                                        post.reply_count += 1
                                        community.post_reply_count += 1
                                        community.last_active = post.last_active = utcnow()
                                        activity_log.result = 'success'
                                        db.session.commit()
                                        vote = PostReplyVote(user_id=user.id, author_id=post_reply.user_id,
                                                             post_reply_id=post_reply.id,
                                                             effect=instance_weight(user.ap_domain))
                                        db.session.add(vote)
                                    else:
                                        activity_log.exception_message = 'Comments disabled'
                        else:
                            activity_log.exception_message = 'Unacceptable type (kbin): ' + object_type
                    else:
                        if user is None or community is None:
                            activity_log.exception_message = 'Blocked or unfound user or community'
                        if user and user.is_local():
                            activity_log.exception_message = 'Activity about local content which is already present'
                            activity_log.result = 'ignored'

                # Announce is new content and votes that happened on a remote server.
                if request_json['type'] == 'Announce':
                    if request_json['object']['type'] == 'Create':
                        activity_log.activity_type = request_json['object']['type']
                        user_ap_id = request_json['object']['object']['attributedTo']
                        community_ap_id = request_json['object']['audience']
                        community = find_actor_or_create(community_ap_id)
                        user = find_actor_or_create(user_ap_id)
                        if (user and not user.is_local()) and community:
                            user.last_seen = community.last_active = site.last_active = utcnow()
                            object_type = request_json['object']['object']['type']
                            new_content_types = ['Page', 'Article', 'Link', 'Note']
                            if object_type in new_content_types:  # create a new post
                                in_reply_to = request_json['object']['object']['inReplyTo'] if 'inReplyTo' in \
                                                                                               request_json['object']['object'] else None

                                if not in_reply_to:
                                    post = Post(user_id=user.id, community_id=community.id,
                                                title=request_json['object']['object']['name'],
                                                comments_enabled=request_json['object']['object']['commentsEnabled'],
                                                sticky=request_json['object']['object']['stickied'] if 'stickied' in request_json['object']['object'] else False,
                                                nsfw=request_json['object']['object']['sensitive'] if 'sensitive' in request_json['object']['object'] else False,
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
                                    if 'image' in request_json['object']['object']:
                                        image = File(source_url=request_json['object']['object']['image']['url'])
                                        db.session.add(image)
                                        post.image = image

                                    if post is not None:
                                        db.session.add(post)
                                        community.post_count += 1
                                        activity_log.result = 'success'
                                        db.session.commit()
                                        if post.image_id:
                                            make_image_sizes(post.image_id, 266, None, 'posts')
                                else:
                                    post_id, parent_comment_id, root_id = find_reply_parent(in_reply_to)
                                    if post_id or parent_comment_id or root_id:
                                        post_reply = PostReply(user_id=user.id, community_id=community.id,
                                                               post_id=post_id, parent_id=parent_comment_id,
                                                               root_id=root_id,
                                                               nsfw=community.nsfw,
                                                               nsfl=community.nsfl,
                                                               ap_id=request_json['object']['object']['id'],
                                                               ap_create_id=request_json['object']['id'],
                                                               ap_announce_id=request_json['id'],
                                                               instance_id=user.instance_id)
                                        if 'source' in request_json['object']['object'] and \
                                                request_json['object']['object']['source']['mediaType'] == 'text/markdown':
                                            post_reply.body = request_json['object']['object']['source']['content']
                                            post_reply.body_html = markdown_to_html(post_reply.body)
                                        elif 'content' in request_json['object']['object']:
                                            post_reply.body_html = allowlist_html(
                                                request_json['object']['object']['content'])
                                            post_reply.body = html_to_markdown(post_reply.body_html)

                                        if post_reply is not None:
                                            post = Post.query.get(post_id)
                                            if post.comments_enabled:
                                                db.session.add(post_reply)
                                                community.post_reply_count += 1
                                                community.last_active = utcnow()
                                                post.last_active = utcnow()
                                                post.reply_count += 1
                                                activity_log.result = 'success'
                                                db.session.commit()
                                            else:
                                                activity_log.exception_message = 'Comments disabled'
                                    else:
                                        activity_log.exception_message = 'Parent not found'
                            else:
                                activity_log.exception_message = 'Unacceptable type: ' + object_type
                        else:
                            if user is None or community is None:
                                activity_log.exception_message = 'Blocked or unfound user or community'
                            if user and user.is_local():
                                activity_log.exception_message = 'Activity about local content which is already present'
                                activity_log.result = 'ignored'

                    elif request_json['object']['type'] == 'Like':
                        activity_log.activity_type = request_json['object']['type']
                        user_ap_id = request_json['object']['actor']
                        liked_ap_id = request_json['object']['object']
                        user = find_actor_or_create(user_ap_id)
                        if user and not user.is_local():
                            liked = find_liked_object(liked_ap_id)
                            # insert into voted table
                            if liked is None:
                                activity_log.exception_message = 'Liked object not found'
                            elif liked is not None and isinstance(liked, Post):
                                upvote_post(liked, user)
                                activity_log.result = 'success'
                            elif liked is not None and isinstance(liked, PostReply):
                                upvote_post_reply(liked, user)
                                activity_log.result = 'success'
                            else:
                                activity_log.exception_message = 'Could not detect type of like'
                            if activity_log.result == 'success':
                                ...
                                # todo: recalculate 'hotness' of liked post/reply
                                # todo: if vote was on content in local community, federate the vote out to followers
                        else:
                            if user is None:
                                activity_log.exception_message = 'Blocked or unfound user'
                            if user and user.is_local():
                                activity_log.exception_message = 'Activity about local content which is already present'
                                activity_log.result = 'ignored'

                    elif request_json['object']['type'] == 'Dislike':
                        activity_log.activity_type = request_json['object']['type']
                        if site.enable_downvotes is False:
                            activity_log.exception_message = 'Dislike ignored because of allow_dislike setting'
                        else:
                            user_ap_id = request_json['object']['actor']
                            liked_ap_id = request_json['object']['object']
                            user = find_actor_or_create(user_ap_id)
                            if user and not user.is_local():
                                disliked = find_liked_object(liked_ap_id)
                                # insert into voted table
                                if disliked is None:
                                    activity_log.exception_message = 'Liked object not found'
                                elif disliked is not None and isinstance(disliked, Post):
                                    downvote_post(disliked, user)
                                    activity_log.result = 'success'
                                elif disliked is not None and isinstance(disliked, PostReply):
                                    downvote_post_reply(disliked, user)
                                    activity_log.result = 'success'
                                else:
                                    activity_log.exception_message = 'Could not detect type of like'
                                if activity_log.result == 'success':
                                    ...  # todo: recalculate 'hotness' of liked post/reply
                                    # todo: if vote was on content in local community, federate the vote out to followers
                            else:
                                if user is None:
                                    activity_log.exception_message = 'Blocked or unfound user'
                                if user and user.is_local():
                                    activity_log.exception_message = 'Activity about local content which is already present'
                                    activity_log.result = 'ignored'
                    elif request_json['object']['type'] == 'Delete':
                        activity_log.activity_type = request_json['object']['type']
                        user_ap_id = request_json['object']['actor']
                        community_ap_id = request_json['object']['audience']
                        to_be_deleted_ap_id = request_json['object']['object']
                        delete_post_or_comment(user_ap_id, community_ap_id, to_be_deleted_ap_id)
                        activity_log.result = 'success'
                    elif request_json['object']['type'] == 'Page': # Editing a post
                        post = Post.query.filter_by(ap_id=request_json['object']['id']).first()
                        if post:
                            post.title = request_json['object']['name']
                            if 'source' in request_json['object'] and request_json['object']['source']['mediaType'] == 'text/markdown':
                                post.body = request_json['object']['source']['content']
                                post.body_html = markdown_to_html(post.body)
                            elif 'content' in request_json['object']:
                                post.body_html = allowlist_html(request_json['object']['content'])
                                post.body = html_to_markdown(post.body_html)
                            if 'attachment' in request_json['object'] and 'href' in request_json['object']['attachment']:
                                post.url = request_json['object']['attachment']['href']
                            post.edited_at = utcnow()
                            db.session.commit()
                            activity_log.result = 'success'
                        else:
                            activity_log.exception_message = 'Post not found'
                    elif request_json['object']['type'] == 'Note':  # Editing a reply
                        reply = PostReply.query.filter_by(ap_id=request_json['object']['id']).first()
                        if reply:
                            if 'source' in request_json['object'] and request_json['object']['source']['mediaType'] == 'text/markdown':
                                reply.body = request_json['object']['source']['content']
                                reply.body_html = markdown_to_html(reply.body)
                            elif 'content' in request_json['object']:
                                reply.body_html = allowlist_html(request_json['object']['content'])
                                reply.body = html_to_markdown(reply.body_html)
                            reply.edited_at = utcnow()
                            db.session.commit()
                            activity_log.result = 'success'
                        else:
                            activity_log.exception_message = 'PostReply not found'
                    else:
                        activity_log.exception_message = 'Invalid type for Announce'

                        # Follow: remote user wants to join/follow one of our communities
                elif request_json['type'] == 'Follow':  # Follow is when someone wants to join a community
                    user_ap_id = request_json['actor']
                    community_ap_id = request_json['object']
                    follow_id = request_json['id']
                    user = find_actor_or_create(user_ap_id)
                    community = find_actor_or_create(community_ap_id)
                    if user is not None and community is not None:
                        # check if user is banned from this community
                        banned = CommunityBan.query.filter_by(user_id=user.id, community_id=community.id).first()
                        if banned is None:
                            user.last_seen = utcnow()
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
                                                            exception_message='could not send Accept' + str(e))
                                db.session.add(accept_log)
                                db.session.commit()
                                return ''
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
                            join_request = CommunityJoinRequest.query.filter_by(user_id=user.id, community_id=community.id).first()
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
                            user.last_seen = utcnow()
                            member = CommunityMember.query.filter_by(user_id=user.id, community_id=community.id).first()
                            join_request = CommunityJoinRequest.query.filter_by(user_id=user.id, community_id=community.id).first()
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
                        if (user and not user.is_local()) and post:
                            user.last_seen = utcnow()
                            existing_vote = PostVote.query.filter_by(user_id=user.id, post_id=post.id).first()
                            if existing_vote:
                                post.author.reputation -= existing_vote.effect
                                if existing_vote.effect < 0:  # Lemmy sends 'like' for upvote and 'dislike' for down votes. Cool! When it undoes an upvote it sends an 'Undo Like'. Fine. When it undoes a downvote it sends an 'Undo Like' - not 'Undo Dislike'?!
                                    post.down_votes -= 1
                                else:
                                    post.up_votes -= 1
                                post.score -= existing_vote.effect
                                db.session.delete(existing_vote)
                                activity_log.result = 'success'
                        if (user and not user.is_local()) and comment:
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
                        else:
                            if user is None or comment is None:
                                activity_log.exception_message = 'Blocked or unfound user or comment'
                            if user and user.is_local():
                                activity_log.exception_message = 'Activity about local content which is already present'
                                activity_log.result = 'ignored'

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
                        if (user and not user.is_local()) and post:
                            existing_vote = PostVote.query.filter_by(user_id=user.id, post_id=post.id).first()
                            if existing_vote:
                                post.author.reputation -= existing_vote.effect
                                post.down_votes -= 1
                                post.score -= existing_vote.effect
                                db.session.delete(existing_vote)
                                activity_log.result = 'success'
                        if (user and not user.is_local()) and comment:
                            existing_vote = PostReplyVote.query.filter_by(user_id=user.id,
                                                                          post_reply_id=comment.id).first()
                            if existing_vote:
                                comment.author.reputation -= existing_vote.effect
                                comment.down_votes -= 1
                                comment.score -= existing_vote.effect
                                db.session.delete(existing_vote)
                                activity_log.result = 'success'

                        if user is None:
                            activity_log.exception_message = 'Blocked or unfound user'
                        if user and user.is_local():
                            activity_log.exception_message = 'Activity about local content which is already present'
                            activity_log.result = 'ignored'

                elif request_json['type'] == 'Update':
                    activity_log.activity_type = 'Update'
                    if request_json['object']['type'] == 'Page':  # Editing a post
                        post = Post.query.filter_by(ap_id=request_json['object']['id']).first()
                        if post:
                            if 'source' in request_json['object'] and request_json['object']['source']['mediaType'] == 'text/markdown':
                                post.body = request_json['object']['source']['content']
                                post.body_html = markdown_to_html(post.body)
                            elif 'content' in request_json['object']:
                                post.body_html = allowlist_html(request_json['object']['content'])
                                post.body = html_to_markdown(post.body_html)
                            if 'attachment' in request_json['object'] and 'href' in request_json['object']['attachment']:
                                post.url = request_json['object']['attachment']['href']
                            post.edited_at = utcnow()
                            db.session.commit()
                            activity_log.result = 'success'
                        else:
                            activity_log.exception_message = 'Post not found'
                    elif request_json['object']['type'] == 'Note':  # Editing a reply
                        reply = PostReply.query.filter_by(ap_id=request_json['object']['id']).first()
                        if reply:
                            if 'source' in request_json['object'] and request_json['object']['source']['mediaType'] == 'text/markdown':
                                reply.body = request_json['object']['source']['content']
                                reply.body_html = markdown_to_html(reply.body)
                            elif 'content' in request_json['object']:
                                reply.body_html = allowlist_html(request_json['object']['content'])
                                reply.body = html_to_markdown(reply.body_html)
                            reply.edited_at = utcnow()
                            db.session.commit()
                            activity_log.result = 'success'
                        else:
                            activity_log.exception_message = 'PostReply not found'
                elif request_json['type'] == 'Delete':
                    if isinstance(request_json['object'], str):
                        ap_id = request_json['object']  # lemmy
                    else:
                        ap_id = request_json['object']['id']  # kbin
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
                elif request_json['type'] == 'Like':  # Upvote
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
                    if (user and not user.is_local()) and post:
                        upvote_post(post, user)
                        activity_log.result = 'success'
                    elif (user and not user.is_local()) and comment:
                        upvote_post_reply(comment, user)
                        activity_log.result = 'success'

                elif request_json['type'] == 'Dislike':  # Downvote
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
                        if (user and not user.is_local()) and comment:
                            downvote_post_reply(comment, user)
                            activity_log.result = 'success'
                        elif (user and not user.is_local()) and post:
                            downvote_post(post, user)
                            activity_log.result = 'success'
                        else:
                            activity_log.exception_message = 'Could not find user or content for vote'
                # Flush the caches of any major object that was created. To be sure.
                if 'user' in vars() and user is not None:
                    user.flush_cache()
                # if 'community' in vars() and community is not None:
                #    community.flush_cache()
                if 'post' in vars() and post is not None:
                    post.flush_cache()
            else:
                activity_log.exception_message = 'Instance banned'

            if activity_log.exception_message is not None and activity_log.result == 'processing':
                activity_log.result = 'failure'
            db.session.commit()


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


@bp.route('/u/<actor>/inbox', methods=['GET', 'POST'])
def user_inbox(actor):
    resp = jsonify('ok')
    resp.content_type = 'application/activity+json'
    return resp


@bp.route('/c/<actor>/inbox', methods=['GET', 'POST'])
def community_inbox(actor):
    return shared_inbox()


@bp.route('/c/<actor>/followers', methods=['GET'])
def community_followers(actor):
    actor = actor.strip()
    community = Community.query.filter_by(name=actor, banned=False, ap_id=None).first()
    if community is not None:
        result = {
            "@context": default_context(),
            "id": f'https://{current_app.config["SERVER_NAME"]}/c/actor/followers',
            "type": "Collection",
            "totalItems": community_members(community.id),
            "items": []
        }
        resp = jsonify(result)
        resp.content_type = 'application/activity+json'
        return resp
    else:
        abort(404)


@bp.route('/comment/<int:comment_id>', methods=['GET'])
def comment_ap(comment_id):
    if is_activitypub_request():
        reply = PostReply.query.get_or_404(comment_id)
        reply_data = {
            "@context": default_context(),
            "type": "Note",
            "id": reply.ap_id,
            "attributedTo": reply.author.profile_id(),
            "inReplyTo": reply.in_reply_to(),
            "to": [
                "https://www.w3.org/ns/activitystreams#Public",
                reply.to()
            ],
            "cc": [
                reply.community.profile_id(),
                reply.author.followers_url()
            ],
            'content': reply.body_html,
            'summary': markdown_to_text(reply.body),
            'mediaType': 'text/html',
            'published': ap_datetime(reply.created_at),
            'distinguished': False,
            'audience': reply.community.profile_id()
        }
        if reply.edited_at:
            reply_data['updated'] = ap_datetime(reply.edited_at)
        if reply.body.strip():
            reply_data['source'] = {
                'content': reply.body,
                'mediaType': 'text/markdown'
            }
        resp = jsonify(reply_data)
        resp.content_type = 'application/activity+json'
        return resp
    else:
        reply = PostReply.query.get(comment_id)
        continue_discussion(reply.post.id, comment_id)


@bp.route('/post/<int:post_id>', methods=['GET', 'POST'])
def post_ap(post_id):
    if request.method == 'GET' and is_activitypub_request():
        post = Post.query.get_or_404(post_id)
        post_data = post_to_activity(post, post.community)
        post_data = post_data['object']['object']
        post_data['@context'] = default_context()
        resp = jsonify(post_data)
        resp.content_type = 'application/activity+json'
        return resp
    else:
        return show_post(post_id)


@bp.route('/activities/<type>/<id>')
@cache.cached(timeout=600)
def activities_json(type, id):
    activity = ActivityPubLog.query.filter_by(activity_id=f"https://{current_app.config['SERVER_NAME']}/activities/{type}/{id}").first()
    if activity:
        activity_json = json.loads(activity.activity_json)
        resp = jsonify(activity_json)
        resp.content_type = 'application/activity+json'
        return resp
    else:
        abort(404)
