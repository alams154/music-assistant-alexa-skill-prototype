"""Vendored Python implementation of music_assistant_api.

This implements the small HTTP API used by Music Assistant for pushing
stream metadata. It mirrors the behavior of the original `server.js`:
optional basic auth, a POST endpoint to push stream metadata and a GET
endpoint to return the latest pushed URL.
"""

from flask import Flask, Blueprint

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


def create_blueprint():
    # Base blueprint for non-/ma endpoints. Keep empty for now.
    bp = Blueprint('music_assistant_api', __name__)
    register_routes(bp)
    return bp


def create_ma_app():
    _ensure_logging_configured()
    app = Flask('music_assistant_api')
    app.register_blueprint(create_blueprint(), url_prefix='')
    return app
