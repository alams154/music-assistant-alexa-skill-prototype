"""Route definitions for music_assistant_api (ma_routes).

This module registers the HTTP endpoints on a provided Flask Blueprint.
It stores the last pushed stream metadata in the shared store and
rewrites internal MA URLs to the public hostname configured via
MA_HOSTNAME.
"""

from flask import jsonify, request
import os
import time
from urllib.parse import urlparse, urlunparse
import shared_store


def _rewrite_url(url: str) -> str:
    """Rewrite internal Music Assistant URLs to the public hostname.

    Replaces the internal host (e.g. http://192.168.1.10:8097) with the
    public MA_HOSTNAME (e.g. music-assistant.example.com) so that Alexa
    devices can reach the stream from the internet.
    """
    if not url:
        return url
    ma_hostname = os.environ.get('MA_HOSTNAME', '').strip()
    if not ma_hostname:
        return url
    try:
        parsed = urlparse(url)
        if not parsed.hostname:
            return url
        # Always use https for the public URL (Alexa requires it)
        rewritten = urlunparse((
            'https',
            ma_hostname,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment
        ))
        return rewritten
    except Exception:
        return url


def register_routes(bp):
    @bp.route('/push-url', methods=['POST'])
    def push_url():
        """Accept JSON with streamUrl and optional metadata and store it.

        Expected JSON body: { streamUrl, title, artist, album, imageUrl }
        """
        data = request.get_json(silent=True) or {}
        stream_url = data.get('streamUrl')
        if not stream_url:
            return jsonify({'error': 'Missing required fields'}), 400

        # Rewrite internal URLs to public hostname before storing
        stream_url = _rewrite_url(stream_url)
        image_url = _rewrite_url(data.get('imageUrl'))

        shared_store._version += 1
        shared_store._store = {
            'streamUrl': stream_url,
            'title': data.get('title'),
            'artist': data.get('artist'),
            'album': data.get('album'),
            'imageUrl': image_url,
            'version': shared_store._version,
            'timestamp': time.time()
        }
        return jsonify({'status': 'ok', 'version': shared_store._version})

    @bp.route('/latest-url', methods=['GET'])
    def latest_url():
        """Return the last pushed stream metadata for the Music Assistant.
        """
        if not shared_store._store:
            return jsonify({'error': 'No URL available'}), 404
        return jsonify(shared_store._store)
