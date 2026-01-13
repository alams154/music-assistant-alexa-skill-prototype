"""Vendored Python implementation of music-assistant-alexa-api.

This implements the small HTTP API used by the Alexa skill and the
Music Assistant push mechanism. It mirrors the behavior of the
original `server.js`: optional basic auth, a POST endpoint to push
stream metadata and a GET endpoint to return the latest pushed URL.

Routes provided:
- POST /ma/push-url        : accept JSON payload with stream metadata
- GET  /ma/latest-url      : return last pushed stream metadata
- GET  /ma/favicon.ico        : serve package favicon if present
"""

from env_secrets import get_env_secret
from flask import Flask, Blueprint, request, Response

from .ma_routes import register_routes


def _unauthorized():
    resp = Response('Access denied', 401)
    resp.headers['WWW-Authenticate'] = 'Basic realm="music-assistant-alexa-api"'
    return resp


def create_blueprint():
    # Base blueprint for non-/ma endpoints. Keep empty for now.
    bp = Blueprint('music_assistant_alexa_api', __name__)
    return bp


def create_ma_blueprint():
    """Create a blueprint with the ma routes and optional basic auth.

    This blueprint is intended to be mounted at the `/ma` path only.
    """
    bp = Blueprint('music_assistant_alexa_api_ma', __name__)

    # Optional basic auth if USERNAME and PASSWORD are provided.
    USERNAME = get_env_secret('API_USERNAME')
    PASSWORD = get_env_secret('API_PASSWORD')

    if USERNAME is not None and PASSWORD is not None:
        @bp.before_request
        def _check_basic_auth():
            auth = request.authorization
            if not auth or auth.username != USERNAME or auth.password != PASSWORD:
                return _unauthorized()

    # Register endpoints implemented in the separate ma_routes module
    register_routes(bp)
    return bp


def create_app():
    # Create and return a base app (no /ma routes mounted here).
    app = Flask('music_assistant_alexa_api')
    app.register_blueprint(create_blueprint(), url_prefix='')
    return app


def create_ma_app():
    """Create a Flask app that exposes only the `/` endpoints from `ma_routes`.

    This app is intended to be mounted under `/ma` by the main application.
    """
    app = Flask('music_assistant_alexa_api_ma')
    app.register_blueprint(create_ma_blueprint(), url_prefix='')
    return app
