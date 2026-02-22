"""Route definitions for music_assistant_api (ma_routes).

This module registers the HTTP endpoints on a provided Flask
`Blueprint`. It stores the last pushed stream metadata in a
module-level `_store` variable.
"""

from flask import jsonify, request
import time


_store = None
_version = 0  # Increment each time new data is pushed


def register_routes(bp):
    @bp.route('/push-url', methods=['POST'])
    def push_url():
        """Accept JSON with streamUrl and optional metadata and store it.

        Expected JSON body: { streamUrl, title, artist, album, imageUrl }
        """
        global _store, _version
        data = request.get_json(silent=True) or {}
        stream_url = data.get('streamUrl')
        if not stream_url:
            return jsonify({'error': 'Missing required fields'}), 400

        _version += 1
        _store = {
            'streamUrl': stream_url,
            'title': data.get('title'),
            'artist': data.get('artist'),
            'album': data.get('album'),
            'imageUrl': data.get('imageUrl'),
            'version': _version,
            'timestamp': time.time()
        }
        return jsonify({'status': 'ok', 'version': _version})

    @bp.route('/latest-url', methods=['GET'])
    def latest_url():
        """Return the last pushed stream metadata for the Music Assistant.
        """
        if not _store:
            return jsonify({'error': 'No URL available, please check if Music Assistant has pushed a URL to the API'}), 404
        return jsonify(_store)
