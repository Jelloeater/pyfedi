import markdown2
import werkzeug.exceptions
from sqlalchemy import text

from app import db
from app.activitypub import bp
from flask import request, Response, current_app, abort, jsonify, json

from app.activitypub.signature import HttpSignature
from app.community.routes import show_community
from app.constants import POST_TYPE_LINK, POST_TYPE_IMAGE
from app.models import User, Community, CommunityJoinRequest, CommunityMember, CommunityBan, ActivityPubLog, Post, \
    PostReply, Instance, PostVote, PostReplyVote, File
from app.activitypub.util import public_key, users_total, active_half_year, active_month, local_posts, local_comments, \
    post_to_activity, find_actor_or_create, default_context, instance_blocked, find_reply_parent, find_liked_object
from app.utils import gibberish, get_setting, is_image_url, allowlist_html, html_to_markdown, render_template, \
    domain_from_url

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
def nodeinfo2():

    nodeinfo_data = {
                "version": "2.0",
                "software": {
                    "name": "pyfedi",
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


@bp.route('/u/<actor>', methods=['GET'])
def user_profile(actor):
    """ Requests to this endpoint can be for a JSON representation of the user, or a HTML rendering of their profile.
    The two types of requests are differentiated by the header """
    actor = actor.strip()
    user = User.query.filter_by(user_name=actor, deleted=False, banned=False, ap_id=None).first()
    if user is not None:
        if 'application/ld+json' in request.headers.get('Accept', '') or request.accept_mimetypes.accept_json:
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
                                "publicKeyPem": user.public_key.replace("\n", "\\n")
                            },
                            "endpoints": {
                                "sharedInbox": f"https://{server}/inbox"
                            },
                            "published": user.created.isoformat()
                        }
            if user.avatar_id is not None:
                actor_data["icon"] = {
                    "type": "Image",
                    "url": f"https://{server}/avatars/{user.avatar.file_path}"
                }
            resp = jsonify(actor_data)
            resp.content_type = 'application/activity+json'
            return resp
        else:
            return render_template('user_profile.html', user=user)


@bp.route('/c/<actor>', methods=['GET'])
def community_profile(actor):
    """ Requests to this endpoint can be for a JSON representation of the community, or a HTML rendering of it.
        The two types of requests are differentiated by the header """
    actor = actor.strip()
    if '@' in actor:
        # don't provide activitypub info for remote communities
        if 'application/ld+json' in request.headers.get('Accept', ''):
            abort(404)
        community = Community.query.filter_by(ap_id=actor, banned=False).first()
    else:
        community = Community.query.filter_by(name=actor, banned=False, ap_id=None).first()
    if community is not None:
        if 'application/ld+json' in request.headers.get('Accept', ''):
            server = current_app.config['SERVER_NAME']
            actor_data = {"@context": default_context(),
                "type": "Group",
                "id": f"https://{server}/c/{actor}",
                "name": actor.title,
                "summary": actor.description,
                "sensitive": True if actor.nsfw or actor.nsfl else False,
                "preferredUsername": actor,
                "inbox": f"https://{server}/c/{actor}/inbox",
                "outbox": f"https://{server}/c/{actor}/outbox",
                "followers": f"https://{server}/c/{actor}/followers",
                "moderators": f"https://{server}/c/{actor}/moderators",
                "featured": f"https://{server}/c/{actor}/featured",
                "attributedTo": f"https://{server}/c/{actor}/moderators",
                "postingRestrictedToMods": actor.restricted_to_mods,
                "url": f"https://{server}/c/{actor}",
                "publicKey": {
                    "id": f"https://{server}/c/{actor}#main-key",
                    "owner": f"https://{server}/c/{actor}",
                    "publicKeyPem": community.public_key.replace("\n", "\\n")
                },
                "endpoints": {
                    "sharedInbox": f"https://{server}/inbox"
                },
                "published": community.created.isoformat(),
                "updated": community.last_active.isoformat(),
            }
            if community.avatar_id is not None:
                actor_data["icon"] = {
                    "type": "Image",
                    "url": f"https://{server}/avatars/{community.avatar.file_path}"
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
                        # Announce is new content and votes
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
                                                        )
                                            if 'source' in request_json['object']['object'] and \
                                                    request_json['object']['object']['source']['mediaType'] == 'text/markdown':
                                                post.body = request_json['object']['object']['source']['content']
                                                post.body_html = allowlist_html(markdown2.markdown(post.body, safe_mode=True))
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
                                                post_reply.body_html = allowlist_html(markdown2.markdown(post_reply.body, safe_mode=True))
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
                                    vote_weight = 1.0
                                    if user.ap_domain:
                                        instance = Instance.query.filter_by(domain=user.ap_domain).fetch()
                                        if instance:
                                            vote_weight = instance.vote_weight
                                    liked = find_liked_object(liked_ap_id)
                                    # insert into voted table
                                    if liked is not None and isinstance(liked, Post):
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

                        # Follow: remote user wants to follow one of our communities
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
                                    if not user.subscribed(community):
                                        member = CommunityMember(user_id=user.id, community_id=community.id)
                                        db.session.add(member)
                                        db.session.commit()
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
                                join_request = CommunityJoinRequest.query.filter_by(user_id=user.id,
                                                                                    community_id=community.id).first()
                                if join_request:
                                    member = CommunityMember(user_id=user.id, community_id=community.id)
                                    db.session.add(member)
                                    community.subscriptions_count += 1
                                    db.session.commit()
                                    activity_log.result = 'success'
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
