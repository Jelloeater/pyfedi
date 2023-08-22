from datetime import datetime

from app.main import bp
from flask import g, jsonify, render_template
from flask_moment import moment
from flask_babel import _, get_locale

from app.models import Community


@bp.before_app_request
def before_request():
    g.locale = str(get_locale())


@bp.route('/', methods=['GET', 'POST'])
@bp.route('/index', methods=['GET', 'POST'])
def index():
    return 'Hello world'


@bp.route('/communities', methods=['GET'])
def list_communities():
    communities = Community.query.all()
    return render_template('list_communities.html', communities=communities)