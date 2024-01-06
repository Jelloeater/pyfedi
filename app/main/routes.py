from datetime import datetime, timedelta
from math import log

from sqlalchemy.sql.operators import or_

from app import db, cache
from app.activitypub.util import default_context, make_image_sizes_async, refresh_user_profile
from app.constants import SUBSCRIPTION_PENDING, SUBSCRIPTION_MEMBER, POST_TYPE_IMAGE, POST_TYPE_LINK, SUBSCRIPTION_OWNER
from app.main import bp
from flask import g, session, flash, request, current_app, url_for, redirect, make_response, jsonify
from flask_moment import moment
from flask_login import current_user
from flask_babel import _, get_locale
from sqlalchemy import select, desc
from sqlalchemy_searchable import search
from app.utils import render_template, get_setting, gibberish, request_etag_matches, return_304, blocked_domains, \
    ap_datetime, ip_address, retrieve_block_list, shorten_string, markdown_to_text
from app.models import Community, CommunityMember, Post, Site, User, utcnow, Domain, Topic


@bp.route('/', methods=['HEAD', 'GET', 'POST'])
@bp.route('/index', methods=['GET', 'POST'])
def index():
    if 'application/ld+json' in request.headers.get('Accept', '') or 'application/activity+json' in request.headers.get(
            'Accept', ''):
        return activitypub_application()

    verification_warning()

    # If nothing has changed since their last visit, return HTTP 304
    current_etag = f"home_{hash(str(g.site.last_active))}"
    if current_user.is_anonymous and request_etag_matches(current_etag):
        return return_304(current_etag)

    page = request.args.get('page', 1, type=int)

    if current_user.is_anonymous:
        flash(_('Create an account to tailor this feed to your interests.'))
        posts = Post.query.filter(Post.from_bot == False, Post.nsfw == False, Post.nsfl == False)
    else:
        posts = Post.query.join(CommunityMember, Post.community_id == CommunityMember.community_id).filter(CommunityMember.is_banned == False)
        posts = posts.join(User, CommunityMember.user_id == User.id).filter(User.id == current_user.id)
        domains_ids = blocked_domains(current_user.id)
        if domains_ids:
            posts = posts.filter(or_(Post.domain_id.not_in(domains_ids), Post.domain_id == None))

    posts = posts.order_by(desc(Post.ranking)).paginate(page=page, per_page=100, error_out=False)

    next_url = url_for('main.index', page=posts.next_num) if posts.has_next else None
    prev_url = url_for('main.index', page=posts.prev_num) if posts.has_prev and page != 1 else None

    active_communities = Community.query.filter_by(banned=False).order_by(desc(Community.last_active)).limit(5).all()

    return render_template('index.html', posts=posts, active_communities=active_communities, show_post_community=True,
                           POST_TYPE_IMAGE=POST_TYPE_IMAGE, POST_TYPE_LINK=POST_TYPE_LINK,
                           SUBSCRIPTION_PENDING=SUBSCRIPTION_PENDING, SUBSCRIPTION_MEMBER=SUBSCRIPTION_MEMBER,
                           etag=f"home_{hash(str(g.site.last_active))}", next_url=next_url, prev_url=prev_url,
                           rss_feed=f"https://{current_app.config['SERVER_NAME']}/feed", rss_feed_name=f"Posts on " + g.site.name,
                           title=f"{g.site.name} - {g.site.description}", description=shorten_string(markdown_to_text(g.site.sidebar), 150))


@bp.route('/new', methods=['HEAD', 'GET', 'POST'])
def new_posts():
    verification_warning()

    # If nothing has changed since their last visit, return HTTP 304
    current_etag = f"new_{hash(str(g.site.last_active))}"
    if current_user.is_anonymous and request_etag_matches(current_etag):
        return return_304(current_etag)

    page = request.args.get('page', 1, type=int)

    if current_user.is_anonymous:
        posts = Post.query.filter(Post.from_bot == False, Post.nsfw == False, Post.nsfl == False)
    else:
        posts = Post.query.join(CommunityMember, Post.community_id == CommunityMember.community_id).filter(
            CommunityMember.is_banned == False)
        posts = posts.join(User, CommunityMember.user_id == User.id).filter(User.id == current_user.id)
        domains_ids = blocked_domains(current_user.id)
        if domains_ids:
            posts = posts.filter(or_(Post.domain_id.not_in(domains_ids), Post.domain_id == None))

    posts = posts.order_by(desc(Post.posted_at)).paginate(page=page, per_page=100, error_out=False)

    next_url = url_for('main.new_posts', page=posts.next_num) if posts.has_next else None
    prev_url = url_for('main.new_posts', page=posts.prev_num) if posts.has_prev and page != 1 else None

    active_communities = Community.query.filter_by(banned=False).order_by(desc(Community.last_active)).limit(5).all()

    return render_template('new_posts.html', posts=posts, active_communities=active_communities,
                           POST_TYPE_IMAGE=POST_TYPE_IMAGE, POST_TYPE_LINK=POST_TYPE_LINK, show_post_community=True,
                           SUBSCRIPTION_PENDING=SUBSCRIPTION_PENDING, SUBSCRIPTION_MEMBER=SUBSCRIPTION_MEMBER,
                           etag=f"home_{hash(str(g.site.last_active))}", next_url=next_url, prev_url=prev_url,
                           rss_feed=f"https://{current_app.config['SERVER_NAME']}/feed",
                           rss_feed_name=f"Posts on " + g.site.name)


@bp.route('/top', methods=['HEAD', 'GET', 'POST'])
def top_posts():
    verification_warning()

    # If nothing has changed since their last visit, return HTTP 304
    current_etag = f"best_{hash(str(g.site.last_active))}"
    if current_user.is_anonymous and request_etag_matches(current_etag):
        return return_304(current_etag)

    page = request.args.get('page', 1, type=int)

    if current_user.is_anonymous:
        posts = Post.query.filter(Post.from_bot == False, Post.nsfw == False, Post.nsfl == False)
    else:
        posts = Post.query.join(CommunityMember, Post.community_id == CommunityMember.community_id).filter(
            CommunityMember.is_banned == False)
        posts = posts.join(User, CommunityMember.user_id == User.id).filter(User.id == current_user.id)
        domains_ids = blocked_domains(current_user.id)
        if domains_ids:
            posts = posts.filter(or_(Post.domain_id.not_in(domains_ids), Post.domain_id == None))

    posts = posts.filter(Post.posted_at > utcnow() - timedelta(days=1)).order_by(desc(Post.score)).paginate(page=page, per_page=100, error_out=False)

    next_url = url_for('main.top_posts', page=posts.next_num) if posts.has_next else None
    prev_url = url_for('main.top_posts', page=posts.prev_num) if posts.has_prev and page != 1 else None

    active_communities = Community.query.filter_by(banned=False).order_by(desc(Community.last_active)).limit(5).all()

    return render_template('top_posts.html', posts=posts, active_communities=active_communities,
                           POST_TYPE_IMAGE=POST_TYPE_IMAGE, POST_TYPE_LINK=POST_TYPE_LINK, show_post_community=True,
                           SUBSCRIPTION_PENDING=SUBSCRIPTION_PENDING, SUBSCRIPTION_MEMBER=SUBSCRIPTION_MEMBER,
                           etag=f"home_{hash(str(g.site.last_active))}", next_url=next_url, prev_url=prev_url,
                           rss_feed=f"https://{current_app.config['SERVER_NAME']}/feed",
                           rss_feed_name=f"Posts on " + g.site.name)


@bp.route('/communities', methods=['GET'])
def list_communities():
    verification_warning()
    search_param = request.args.get('search', '')
    topic_id = int(request.args.get('topic_id', 0))
    topics = Topic.query.order_by(Topic.name).all()
    if search_param == '':
        pass
    else:
        flash('Sorry, no search function yet. Use the topic filter for now.', 'warning')
        communities = Community.query.filter_by(banned=False).all()
        #query = search(select(Community), search_param, sort=True)  # todo: exclude banned communities from search
        #communities = db.session.scalars(query).all()

    communities = Community.query.filter_by(banned=False)
    if topic_id != 0:
        communities = communities.filter_by(topic_id=topic_id)

    return render_template('list_communities.html', communities=communities.all(), search=search_param, title=_('Communities'),
                           SUBSCRIPTION_PENDING=SUBSCRIPTION_PENDING, SUBSCRIPTION_MEMBER=SUBSCRIPTION_MEMBER,
                           SUBSCRIPTION_OWNER=SUBSCRIPTION_OWNER, topics=topics, topic_id=topic_id)


@bp.route('/communities/local', methods=['GET'])
def list_local_communities():
    verification_warning()
    communities = Community.query.filter_by(ap_id=None, banned=False).all()
    return render_template('list_communities.html', communities=communities, title=_('Local communities'),
                           SUBSCRIPTION_PENDING=SUBSCRIPTION_PENDING, SUBSCRIPTION_MEMBER=SUBSCRIPTION_MEMBER)


@bp.route('/communities/subscribed', methods=['GET'])
def list_subscribed_communities():
    verification_warning()
    if current_user.is_authenticated:
        communities = Community.query.filter_by(banned=False).join(CommunityMember).filter(CommunityMember.user_id == current_user.id).all()
    else:
        communities = []
    return render_template('list_communities.html', communities=communities, title=_('Joined communities'),
                           SUBSCRIPTION_PENDING=SUBSCRIPTION_PENDING, SUBSCRIPTION_MEMBER=SUBSCRIPTION_MEMBER)


@bp.route('/donate')
def donate():
    return render_template('donate.html')


@bp.route('/privacy')
def privacy():
    return render_template('privacy.html')


@bp.route('/login')
def login():
    return redirect(url_for('auth.login'))


@bp.route('/robots.txt')
def robots():
    resp = make_response(render_template('robots.txt'))
    resp.mimetype = 'text/plain'
    return resp


@bp.route('/test')
def test():
    return 'done'

    #ip = request.headers.get('X-Forwarded-For') or request.remote_addr
    #if ',' in ip:  # Remove all but first ip addresses
    #    ip = ip[:ip.index(',')].strip()
    #return ip


def verification_warning():
    if hasattr(current_user, 'verified') and current_user.verified is False:
        flash(_('Please click the link in your email inbox to verify your account.'), 'warning')


@cache.cached(timeout=6)
def activitypub_application():
    application_data = {
        '@context': default_context(),
        'type': 'Application',
        'id': f"https://{current_app.config['SERVER_NAME']}/",
        'name': g.site.name,
        'summary': g.site.description,
        'published': ap_datetime(g.site.created_at),
        'updated': ap_datetime(g.site.updated),
        'inbox': f"https://{current_app.config['SERVER_NAME']}/site_inbox",
        'outbox': f"https://{current_app.config['SERVER_NAME']}/site_outbox",
    }
    resp = jsonify(application_data)
    resp.content_type = 'application/activity+json'
    return resp
