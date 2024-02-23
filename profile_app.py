#!flask/bin/python
import os

from flask import session, g, json
from flask_babel import get_locale
from werkzeug.middleware.profiler import ProfilerMiddleware
from app import create_app, db, cli
from app.models import Site
from app.utils import gibberish, shorten_number, community_membership, getmtime, digits, user_access, ap_datetime, \
    can_create_post, can_upvote, can_downvote, current_theme, shorten_string, shorten_url

app = create_app()

with app.app_context():
    app.jinja_env.globals['getmtime'] = getmtime
    app.jinja_env.globals['len'] = len
    app.jinja_env.globals['digits'] = digits
    app.jinja_env.globals['str'] = str
    app.jinja_env.globals['shorten_number'] = shorten_number
    app.jinja_env.globals['community_membership'] = community_membership
    app.jinja_env.globals['json_loads'] = json.loads
    app.jinja_env.globals['user_access'] = user_access
    app.jinja_env.globals['ap_datetime'] = ap_datetime
    app.jinja_env.globals['can_create'] = can_create_post
    app.jinja_env.globals['can_upvote'] = can_upvote
    app.jinja_env.globals['can_downvote'] = can_downvote
    app.jinja_env.globals['theme'] = current_theme
    app.jinja_env.globals['file_exists'] = os.path.exists
    app.jinja_env.filters['shorten'] = shorten_string
    app.jinja_env.filters['shorten_url'] = shorten_url
    app.config['PROFILE'] = True
    app.wsgi_app = ProfilerMiddleware(app.wsgi_app, restrictions=[30])
    app.run(debug = True, host='127.0.0.1')



@app.before_request
def before_request():
    session['nonce'] = gibberish()
    g.locale = str(get_locale())
    g.site = Site.query.get(1)