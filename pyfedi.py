# This file is part of pyfedi, which is licensed under the GNU General Public License (GPL) version 3.0.
# You should have received a copy of the GPL along with this program. If not, see <http://www.gnu.org/licenses/>.
from flask_babel import get_locale

from app import create_app, db, cli
import os, click
from flask import session, g, json
from app.constants import POST_TYPE_LINK, POST_TYPE_IMAGE, POST_TYPE_ARTICLE
from app.models import Site
from app.utils import getmtime, gibberish, shorten_string, shorten_url, digits, user_access, community_membership

app = create_app()
cli.register(app)


@app.context_processor
def app_context_processor():
    def getmtime(filename):
        return os.path.getmtime('app/static/' + filename)
    return dict(getmtime=getmtime, post_type_link=POST_TYPE_LINK, post_type_image=POST_TYPE_IMAGE, post_type_article=POST_TYPE_ARTICLE)


@app.shell_context_processor
def make_shell_context():
    return {'db': db, 'app': app}


with app.app_context():
    app.jinja_env.globals['getmtime'] = getmtime
    app.jinja_env.globals['len'] = len
    app.jinja_env.globals['digits'] = digits
    app.jinja_env.globals['str'] = str
    app.jinja_env.globals['community_membership'] = community_membership
    app.jinja_env.globals['json_loads'] = json.loads
    app.jinja_env.globals['user_access'] = user_access
    app.jinja_env.filters['shorten'] = shorten_string
    app.jinja_env.filters['shorten_url'] = shorten_url


@app.before_request
def before_request():
    session['nonce'] = gibberish()
    g.locale = str(get_locale())
    g.site = Site.query.get(1)


@app.after_request
def after_request(response):
    response.headers['Content-Security-Policy'] = f"script-src 'self' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net 'nonce-{session['nonce']}'"
    response.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains; preload'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    return response
