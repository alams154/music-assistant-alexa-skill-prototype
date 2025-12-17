"""Minimal vendored Python implementation of music-assistant-alexa-api.

This provides a small Flask blueprint and app factory exposing the
`/latest-url` endpoint expected by the skill's `/status` check.
"""
import os
from flask import Flask, Blueprint, jsonify


def create_blueprint():
    bp = Blueprint('music_assistant_alexa_api', __name__)

    @bp.route('/latest-url', methods=['GET'])
    def latest_url():
        """Return a JSON object containing the latest stream URL.
        """
        url = os.environ.get('MA_STREAM_URL') or os.environ.get('API_HOSTNAME')
        return jsonify({'url': url}), 200

    return bp


def create_app():
    app = Flask('music_assistant_alexa_api')
    app.register_blueprint(create_blueprint(), url_prefix='')
    return app
