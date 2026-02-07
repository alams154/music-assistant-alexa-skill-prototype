"""Simple Alexa-oriented API package.

This package provides a small Flask app/blueprint intended to be
mounted at `/alexa`. It is separate from the Music Assistant API which
is mounted at `/ma`.
"""

from flask import Flask, Blueprint
import logging
from .alexa_routes import register_routes


def _ensure_logging_configured():
    root = logging.getLogger()
    # avoid duplicate filter if already configured
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


def create_blueprint():
    bp = Blueprint('alexa_api', __name__)
    # Register Alexa-specific endpoints implemented in alexa_routes
    register_routes(bp)
    return bp


def create_alexa_app():
    _ensure_logging_configured()
    app = Flask('alexa_api')
    app.register_blueprint(create_blueprint(), url_prefix='')
    return app
