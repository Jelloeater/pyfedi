from flask import Blueprint

bp = Blueprint('topic', __name__)

from app.topic import routes
