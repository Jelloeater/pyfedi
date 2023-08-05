from flask import Blueprint

bp = Blueprint('activitypub', __name__)

from app.activitypub import routes
