"""Vendored Python implementation of music_assistant_api.

This implements the small HTTP API used by Music Assistant for pushing
stream metadata. It mirrors the behavior of the original `server.js`:
optional basic auth, a POST endpoint to push stream metadata and a GET
endpoint to return the latest pushed URL.
"""

from flask import Flask, Blueprint, Response

from .ma_routes import register_routes
import logging


def _ensure_logging_configured():
    """Configure logging format and a component filter for API runs.

    If the application is run standalone the lambda-based logging setup
    from `lambda_function` won't be present, so configure a compatible
    format here and add the same `component` field.
    """
    root = logging.getLogger()
    # If a filter already injected `component`, skip reconfiguration
    for f in root.filters:
        if getattr(f, '__name__', '') == '_ComponentFilter':
            return

    class _ComponentFilter(logging.Filter):
        def filter(self, record):
            name = (record.name or "")
            if name.startswith('music_assistant_api') or name.startswith('ma_routes'):
                record.component = 'API'
            elif name.startswith('skill') or name == 'lambda_function' or name.startswith('ask_sdk'):
                record.component = 'Skill'
            else:
                record.component = 'UI/Web'
            return True

    root.addFilter(_ComponentFilter())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(component)s] %(name)s %(message)s"
    )


def _unauthorized():
    resp = Response('Access denied', 401)
    resp.headers['WWW-Authenticate'] = 'Basic realm="music-assistant-api"'
    return resp


def create_blueprint():
    # Base blueprint for non-/ma endpoints. Keep empty for now.
    bp = Blueprint('music_assistant_api', __name__)
    return bp


def create_ma_blueprint():
    """Create a blueprint with the ma routes and optional basic auth.

    This blueprint is intended to be mounted at the `/ma` path only.
    """
    bp = Blueprint('music_assistant_api_ma', __name__)

    # No basic auth enforced at the MA blueprint level; app-level auth is applied
    # by the main application so the MA API runs without its own auth here.

    # Register endpoints implemented in the separate ma_routes module
    register_routes(bp)
    return bp


def create_app():
    # Create and return a base app (no /ma routes mounted here).
    _ensure_logging_configured()
    app = Flask('music_assistant_api')
    app.register_blueprint(create_blueprint(), url_prefix='')
    return app


def create_ma_app():
    """Create a Flask app that exposes only the `/` endpoints from `ma_routes`.

    This app is intended to be mounted under `/ma` by the main application.
    """
    _ensure_logging_configured()
    app = Flask('music_assistant_api_ma')
    app.register_blueprint(create_ma_blueprint(), url_prefix='')
    return app
