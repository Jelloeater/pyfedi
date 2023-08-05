from sqlalchemy import text

from app import db
from app.activitypub import bp
from flask import request, Response, render_template, current_app, abort, jsonify
from app.models import User, Community
from app.activitypub.util import public_key

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
    users_total = db.session.execute(text('SELECT COUNT(id) as c FROM "user" WHERE ap_id is null AND verified is true AND banned is false AND deleted is false')).scalar()
    active_half_year = db.session.execute(text("SELECT COUNT(id) as c FROM \"user\" WHERE last_seen >= CURRENT_DATE - INTERVAL '6 months' AND ap_id is null AND verified is true AND banned is false AND deleted is false")).scalar()
    active_month     = db.session.execute(text("SELECT COUNT(id) as c FROM \"user\" WHERE last_seen >= CURRENT_DATE - INTERVAL '1 month' AND ap_id is null AND verified is true AND banned is false AND deleted is false")).scalar()
    local_posts = db.session.execute(text('SELECT COUNT(id) as c FROM "post" WHERE ap_id is null')).scalar()
    local_comments = db.session.execute(text('SELECT COUNT(id) as c FROM "post_reply" WHERE ap_id is null')).scalar()

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
                        "total": users_total,
                        "activeHalfyear": active_half_year,
                        "activeMonth": active_month
                    },
                    "localPosts": local_posts,
                    "localComments": local_comments
                },
                "openRegistrations": True
            }
    return jsonify(nodeinfo_data)


@bp.route('/users/<actor>', methods=['GET'])
def return_actor(actor):
    """ This returns the actor.json object when somebody in the
    Fediverse searches for this user. It returns the paths of
    this user's inbox, its preferred username, the user's public key
    and a profile image """

    preferredUsername = actor  # but could become a custom username, set by the user, stored in the database this preferredUsername doesn't show up yet in Mastodon ...
    json = render_template('actor.json', actor=actor, preferredUsername=preferredUsername, publicKey=public_key(),
                           domain=current_app.config['SERVER_NAME'])  # actor = alice
    resp = Response(json, status=200, mimetype='application/json')
    return resp


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
