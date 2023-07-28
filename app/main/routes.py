from app.main import bp
from flask import g
from flask_moment import moment
from flask_babel import _, get_locale


@bp.before_app_request
def before_request():
    g.locale = str(get_locale())


@bp.route('/', methods=['GET', 'POST'])
@bp.route('/index', methods=['GET', 'POST'])
def index():
    return 'Hello world'
