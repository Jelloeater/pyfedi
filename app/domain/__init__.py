from flask import Blueprint

bp = Blueprint('domain', __name__)

from app.domain import routes
