# This file is part of pyfedi, which is licensed under the GNU General Public License (GPL) version 3.0.
# You should have received a copy of the GPL along with this program. If not, see <http://www.gnu.org/licenses/>.


from app import create_app, db, cli
import os

app = create_app()
cli.register(app)


@app.context_processor
def app_context_processor():  # NB there needs to be an identical function in cb.wsgi to make this work in production
    def getmtime(filename):
        return os.path.getmtime('app/static/' + filename)
    return dict(getmtime=getmtime)


@app.shell_context_processor
def make_shell_context():
    return {'db': db}
