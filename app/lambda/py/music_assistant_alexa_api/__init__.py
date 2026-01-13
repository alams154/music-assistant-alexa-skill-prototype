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

import os
from env_secrets import get_env_secret
from flask import Flask, Blueprint, jsonify, request, Response, send_file


_store = None


def _unauthorized():
    resp = Response('Access denied', 401)
    resp.headers['WWW-Authenticate'] = 'Basic realm="music-assistant-alexa-api"'
    return resp


def create_blueprint():
    bp = Blueprint('music_assistant_alexa_api', __name__)

    # Optional basic auth if USERNAME and PASSWORD are provided.
    USERNAME = get_env_secret('API_USERNAME')
    PASSWORD = get_env_secret('API_PASSWORD')

    if USERNAME is not None and PASSWORD is not None:
        @bp.before_request
        def _check_basic_auth():
            auth = request.authorization
            if not auth or auth.username != USERNAME or auth.password != PASSWORD:
                return _unauthorized()

    @bp.route('/favicon.ico', methods=['GET'])
    def favicon():
        # Try to serve a favicon located next to this package; if missing,
        # return an empty 204 so clients don't keep retrying.
        pkg_root = os.path.dirname(__file__)
        fav_path = os.path.join(pkg_root, 'favicon.ico')
        if os.path.exists(fav_path):
            return send_file(fav_path)
        return ('', 204)

    @bp.route('/push-url', methods=['POST'])
    def push_url():
        """Accept JSON with streamUrl and optional metadata and store it.

        Expected JSON body: { streamUrl, title, artist, album, imageUrl }
        """
        global _store
        data = request.get_json(silent=True) or {}
        stream_url = data.get('streamUrl')
        if not stream_url:
            return jsonify({'error': 'Missing required fields'}), 400

        _store = {
            'streamUrl': stream_url,
            'title': data.get('title'),
            'artist': data.get('artist'),
            'album': data.get('album'),
            'imageUrl': data.get('imageUrl'),
        }
        print('Received:', _store)
        return jsonify({'status': 'ok'})

    @bp.route('/latest-url', methods=['GET'])
    def latest_url_ma():
        """Return the last pushed stream metadata for the Alexa skill.
        """
        if not _store:
            return jsonify({'error': 'No URL available, please check if Music Assistant has pushed a URL to the API'}), 404
        return jsonify(_store)

    return bp


def create_app():
    app = Flask('music_assistant_alexa_api')
    app.register_blueprint(create_blueprint(), url_prefix='')
    return app
