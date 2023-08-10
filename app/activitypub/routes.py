from sqlalchemy import text

from app import db
from app.activitypub import bp
from flask import request, Response, render_template, current_app, abort, jsonify
from app.models import User, Community
from app.activitypub.util import public_key, users_total, active_half_year, active_month, local_posts, local_comments, \
    post_to_activity

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
            actor_data = {  "@context": [
                                "https://www.w3.org/ns/activitystreams",
                                "https://w3id.org/security/v1",
                                {
                                    "manuallyApprovesFollowers": "as:manuallyApprovesFollowers",
                                    "schema": "http://schema.org#",
                                    "PropertyValue": "schema:PropertyValue",
                                    "value": "schema:value"
                                }
                            ],
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
    community = Community.query.filter_by(name=actor, banned=False, ap_id=None).first()
    if community is not None:
        if 'application/ld+json' in request.headers.get('Accept', '') or request.accept_mimetypes.accept_json:
            server = current_app.config['SERVER_NAME']
            actor_data = {"@context": [
                "https://www.w3.org/ns/activitystreams",
                "https://w3id.org/security/v1",
                {
                    "manuallyApprovesFollowers": "as:manuallyApprovesFollowers",
                    "schema": "http://schema.org#",
                    "PropertyValue": "schema:PropertyValue",
                    "value": "schema:value"
                }
                ],
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
        else:
            return render_template('user_profile.html', user=community)


@bp.route('/c/<actor>/outbox', methods=['GET'])
def community_outbox(actor):
    actor = actor.strip()
    community = Community.query.filter_by(name=actor, banned=False, ap_id=None).first()
    if community is not None:
        posts = community.posts.limit(50).all()

        community_data = {
            "@context": [
                "https://www.w3.org/ns/activitystreams",
                "https://w3id.org/security/v1",
                {
                    "lemmy": "https://join-lemmy.org/ns#",
                    "pt": "https://joinpeertube.org/ns#",
                    "sc": "http://schema.org/",
                    "commentsEnabled": "pt:commentsEnabled",
                    "sensitive": "as:sensitive",
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
                }
            ],
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
