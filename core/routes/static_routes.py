"""Static asset and index page routes."""

from flask import Blueprint, send_from_directory, current_app

bp = Blueprint('static', __name__)


@bp.route('/')
def index():
    return send_from_directory(current_app.static_folder, 'index.html')


@bp.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory(current_app.static_folder, path)
