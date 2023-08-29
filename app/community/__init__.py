from flask import Blueprint

bp = Blueprint('community', __name__)

from app.community import routes
