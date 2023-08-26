from datetime import datetime

from app.main import bp
from flask import g, jsonify, render_template, flash
from flask_moment import moment
from flask_login import current_user
from flask_babel import _, get_locale

from app.models import Community


@bp.before_app_request
def before_request():
    g.locale = str(get_locale())


@bp.route('/', methods=['GET', 'POST'])
@bp.route('/index', methods=['GET', 'POST'])
def index():
    if hasattr(current_user, 'verified') and current_user.verified is False:
        flash(_('Please click the link in your email inbox to verify your account.'), 'warning')
    return render_template('index.html')


@bp.route('/communities', methods=['GET'])
def list_communities():
    communities = Community.query.all()
    return render_template('list_communities.html', communities=communities)