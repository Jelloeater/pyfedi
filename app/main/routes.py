import os.path
from datetime import datetime, timedelta
from math import log
from random import randint

from sqlalchemy.sql.operators import or_

from app import db, cache
from app.activitypub.util import default_context, make_image_sizes_async, refresh_user_profile, find_actor_or_create
from app.constants import SUBSCRIPTION_PENDING, SUBSCRIPTION_MEMBER, POST_TYPE_IMAGE, POST_TYPE_LINK, \
    SUBSCRIPTION_OWNER, SUBSCRIPTION_MODERATOR
from app.inoculation import inoculation
from app.main import bp
from flask import g, session, flash, request, current_app, url_for, redirect, make_response, jsonify
from flask_moment import moment
from flask_login import current_user
from flask_babel import _, get_locale
from sqlalchemy import select, desc, text
from sqlalchemy_searchable import search
from app.utils import render_template, get_setting, gibberish, request_etag_matches, return_304, blocked_domains, \
    ap_datetime, ip_address, retrieve_block_list, shorten_string, markdown_to_text, user_filters_home, \
    joined_communities, moderating_communities, parse_page, theme_list, get_request
from app.models import Community, CommunityMember, Post, Site, User, utcnow, Domain, Topic, File, Instance, \
    InstanceRole, Notification
from PIL import Image
import pytesseract


@bp.route('/', methods=['HEAD', 'GET', 'POST'])
@bp.route('/home', methods=['GET', 'POST'])
@bp.route('/home/<sort>', methods=['GET', 'POST'])
def index(sort=None):
    if 'application/ld+json' in request.headers.get('Accept', '') or 'application/activity+json' in request.headers.get(
            'Accept', ''):
        return activitypub_application()

    return home_page('home', sort)


@bp.route('/popular', methods=['GET'])
@bp.route('/popular/<sort>', methods=['GET'])
def popular(sort=None):
    return home_page('popular', sort)


@bp.route('/all', methods=['GET'])
@bp.route('/all/<sort>', methods=['GET'])
def all_posts(sort=None):
    return home_page('all', sort)


def home_page(type, sort):
    verification_warning()

    if sort is None:
        sort = current_user.default_sort if current_user.is_authenticated else 'hot'

    # If nothing has changed since their last visit, return HTTP 304
    current_etag = f"{type}_{sort}_{hash(str(g.site.last_active))}"
    if current_user.is_anonymous and request_etag_matches(current_etag):
        return return_304(current_etag)

    page = request.args.get('page', 1, type=int)
    low_bandwidth = request.cookies.get('low_bandwidth', '0') == '1'

    if current_user.is_anonymous:
        flash(_('Create an account to tailor this feed to your interests.'))
        posts = Post.query.filter(Post.from_bot == False, Post.nsfw == False, Post.nsfl == False)
        posts = posts.join(Community, Community.id == Post.community_id)
        if type == 'home':
            posts = posts.filter(Community.show_home == True)
        elif type == 'popular':
            posts = posts.filter(Community.show_popular == True).filter(Post.score > 100)
        elif type == 'all':
            posts = posts.filter(Community.show_all == True)
        content_filters = {}
    else:
        if type == 'home':
            posts = Post.query.join(CommunityMember, Post.community_id == CommunityMember.community_id).filter(
                CommunityMember.is_banned == False)
            # posts = posts.join(User, CommunityMember.user_id == User.id).filter(User.id == current_user.id)
            posts = posts.filter(CommunityMember.user_id == current_user.id)
        elif type == 'popular':
            posts = Post.query.filter(Post.from_bot == False)
            posts = posts.join(Community, Community.id == Post.community_id)
            posts = posts.filter(Community.show_popular == True, Post.score > 100)
        elif type == 'all':
            posts = Post.query
            posts = posts.join(Community, Community.id == Post.community_id)
            posts = posts.filter(Community.show_all == True)

        if current_user.ignore_bots:
            posts = posts.filter(Post.from_bot == False)
        if current_user.show_nsfl is False:
            posts = posts.filter(Post.nsfl == False)
        if current_user.show_nsfw is False:
            posts = posts.filter(Post.nsfw == False)

        domains_ids = blocked_domains(current_user.id)
        if domains_ids:
            posts = posts.filter(or_(Post.domain_id.not_in(domains_ids), Post.domain_id == None))
        content_filters = user_filters_home(current_user.id)

    # Sorting
    if sort == 'hot':
        posts = posts.order_by(desc(Post.ranking)).order_by(desc(Post.posted_at))
    elif sort == 'top':
        posts = posts.filter(Post.posted_at > utcnow() - timedelta(days=1)).order_by(desc(Post.score))
    elif sort == 'new':
        posts = posts.order_by(desc(Post.posted_at))
    elif sort == 'active':
        posts = posts.order_by(desc(Post.last_active))

    # Pagination
    posts = posts.paginate(page=page, per_page=100 if current_user.is_authenticated and not low_bandwidth else 50, error_out=False)
    if type == 'home':
        next_url = url_for('main.index', page=posts.next_num, sort=sort) if posts.has_next else None
        prev_url = url_for('main.index', page=posts.prev_num, sort=sort) if posts.has_prev and page != 1 else None
    elif type == 'popular':
        next_url = url_for('main.popular', page=posts.next_num, sort=sort) if posts.has_next else None
        prev_url = url_for('main.popular', page=posts.prev_num, sort=sort) if posts.has_prev and page != 1 else None
    elif type == 'all':
        next_url = url_for('main.all_posts', page=posts.next_num, sort=sort) if posts.has_next else None
        prev_url = url_for('main.all_posts', page=posts.prev_num, sort=sort) if posts.has_prev and page != 1 else None

    active_communities = Community.query.filter_by(banned=False).order_by(desc(Community.last_active)).limit(5).all()

    return render_template('index.html', posts=posts, active_communities=active_communities, show_post_community=True,
                           POST_TYPE_IMAGE=POST_TYPE_IMAGE, POST_TYPE_LINK=POST_TYPE_LINK,
                           low_bandwidth=low_bandwidth,
                           SUBSCRIPTION_PENDING=SUBSCRIPTION_PENDING, SUBSCRIPTION_MEMBER=SUBSCRIPTION_MEMBER,
                           etag=f"{type}_{sort}_{hash(str(g.site.last_active))}", next_url=next_url, prev_url=prev_url,
                           rss_feed=f"https://{current_app.config['SERVER_NAME']}/feed",
                           rss_feed_name=f"Posts on " + g.site.name,
                           title=f"{g.site.name} - {g.site.description}",
                           description=shorten_string(markdown_to_text(g.site.sidebar), 150),
                           content_filters=content_filters, type=type, sort=sort,
                           moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id()),
                           inoculation=inoculation[randint(0, len(inoculation) - 1)])


@bp.route('/topics', methods=['GET'])
def list_topics():
    verification_warning()
    topics = Topic.query.order_by(Topic.name).all()

    return render_template('list_topics.html', topics=topics, title=_('Browse by topic'),
                           low_bandwidth=request.cookies.get('low_bandwidth', '0') == '1',
                           moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id()))


@bp.route('/communities', methods=['GET'])
def list_communities():
    verification_warning()
    search_param = request.args.get('search', '')
    topic_id = int(request.args.get('topic_id', 0))
    sort_by = text('community.' + request.args.get('sort_by') if request.args.get('sort_by') else 'community.post_reply_count desc')
    topics = Topic.query.order_by(Topic.name).all()
    communities = Community.query.filter_by(banned=False)
    if search_param == '':
        pass
    else:
        communities = communities.filter(or_(Community.title.ilike(f"%{search_param}%"), Community.ap_id.ilike(f"%{search_param}%")))
        #query = search(select(Community), search_param, sort=True)  # todo: exclude banned communities from search
        #communities = db.session.scalars(query).all()


    if topic_id != 0:
        communities = communities.filter_by(topic_id=topic_id)

    return render_template('list_communities.html', communities=communities.order_by(sort_by).all(), search=search_param, title=_('Communities'),
                           SUBSCRIPTION_PENDING=SUBSCRIPTION_PENDING, SUBSCRIPTION_MEMBER=SUBSCRIPTION_MEMBER,
                           SUBSCRIPTION_OWNER=SUBSCRIPTION_OWNER, SUBSCRIPTION_MODERATOR=SUBSCRIPTION_MODERATOR,
                           topics=topics, topic_id=topic_id, sort_by=sort_by,
                           low_bandwidth=request.cookies.get('low_bandwidth', '0') == '1', moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id()))


@bp.route('/communities/local', methods=['GET'])
def list_local_communities():
    verification_warning()
    sort_by = text('community.' + request.args.get('sort_by') if request.args.get('sort_by') else 'community.post_reply_count desc')
    communities = Community.query.filter_by(ap_id=None, banned=False)
    return render_template('list_communities.html', communities=communities.order_by(sort_by).all(), title=_('Local communities'), sort_by=sort_by,
                           SUBSCRIPTION_PENDING=SUBSCRIPTION_PENDING, SUBSCRIPTION_MEMBER=SUBSCRIPTION_MEMBER,
                            SUBSCRIPTION_MODERATOR=SUBSCRIPTION_MODERATOR,
                           low_bandwidth=request.cookies.get('low_bandwidth', '0') == '1', moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id()))


@bp.route('/communities/subscribed', methods=['GET'])
def list_subscribed_communities():
    verification_warning()
    sort_by = text('community.' + request.args.get('sort_by') if request.args.get('sort_by') else 'community.post_reply_count desc')
    if current_user.is_authenticated:
        communities = Community.query.filter_by(banned=False).join(CommunityMember).filter(CommunityMember.user_id == current_user.id)
    else:
        communities = []
    return render_template('list_communities.html', communities=communities.order_by(sort_by).all(), title=_('Joined communities'),
                           SUBSCRIPTION_PENDING=SUBSCRIPTION_PENDING, SUBSCRIPTION_MEMBER=SUBSCRIPTION_MEMBER, sort_by=sort_by,
                           SUBSCRIPTION_MODERATOR=SUBSCRIPTION_MODERATOR,
                           low_bandwidth=request.cookies.get('low_bandwidth', '0') == '1', moderating_communities=moderating_communities(current_user.get_id()),
                           joined_communities=joined_communities(current_user.get_id()))


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


@bp.route('/sitemap.xml')
@cache.cached(timeout=6000)
def sitemap():
    posts = Post.query.filter(Post.from_bot == False)
    posts = posts.join(Community, Community.id == Post.community_id)
    posts = posts.filter(Community.show_all == True, Community.ap_id == None)   # sitemap.xml only includes local posts
    if not g.site.enable_nsfw:
        posts = posts.filter(Community.nsfw == False)
    if not g.site.enable_nsfl:
        posts = posts.filter(Community.nsfl == False)
    posts = posts.order_by(desc(Post.posted_at))

    resp = make_response(render_template('sitemap.xml', posts=posts, current_app=current_app))
    resp.mimetype = 'text/xml'
    return resp


@bp.route('/keyboard_shortcuts')
def keyboard_shortcuts():
    return render_template('keyboard_shortcuts.html')


def list_files(directory):
    for root, dirs, files in os.walk(directory):
        for file in files:
            yield os.path.join(root, file)


@bp.route('/test')
def test():
    u = User.query.filter(User.email_unread == True).join(Notification, Notification.user_id == User.id).filter()
    return 'ok'


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
