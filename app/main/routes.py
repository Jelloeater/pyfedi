from datetime import datetime

from app import db
from app.main import bp
from flask import g, session, flash, request
from flask_moment import moment
from flask_login import current_user
from flask_babel import _, get_locale
from sqlalchemy import select
from sqlalchemy_searchable import search
from app.utils import render_template, get_setting, gibberish

from app.models import Community, CommunityMember


@bp.route('/', methods=['GET', 'POST'])
@bp.route('/index', methods=['GET', 'POST'])
def index():
    if hasattr(current_user, 'verified') and current_user.verified is False:
        flash(_('Please click the link in your email inbox to verify your account.'), 'warning')
    return render_template('index.html')


@bp.route('/communities', methods=['GET'])
def list_communities():
    search_param = request.args.get('search', '')
    if search_param == '':
        communities = Community.query.filter_by(banned=False).all()
    else:
        query = search(select(Community), search_param, sort=True)
        communities = db.session.scalars(query).all()

    return render_template('list_communities.html', communities=communities, search=search_param, title=_('Communities'))


@bp.route('/communities/local', methods=['GET'])
def list_local_communities():
    communities = Community.query.filter_by(ap_id=None, banned=False).all()
    return render_template('list_communities.html', communities=communities, title=_('Local communities'))


@bp.route('/communities/subscribed', methods=['GET'])
def list_subscribed_communities():
    communities = Community.query.filter_by(banned=False).join(CommunityMember).filter(CommunityMember.user_id == current_user.id).all()
    return render_template('list_communities.html', communities=communities, title=_('Subscribed communities'))
