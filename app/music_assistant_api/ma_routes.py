"""Route definitions for music_assistant_api (ma_routes)."""

from flask import jsonify, request
import time
import shared_store


def _rewrite_url(url: str) -> str:
    """Rewrite local Music Assistant stream URLs to the public MA_HOSTNAME prefix."""
    if not url:
        return url
    try:
        from skill.util import get_ma_hostname, replace_ip_in_url
        hostname = get_ma_hostname()
        if not hostname:
            return url
        return replace_ip_in_url(url, hostname)
    except Exception:
        return url


def register_routes(bp):
    @bp.route('/push-url', methods=['POST'])
    def push_url():
        data = request.get_json(silent=True) or {}
        stream_url = data.get('streamUrl')
        if not stream_url:
            return jsonify({'error': 'Missing required fields'}), 400

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
        if not shared_store._store:
            return jsonify({'error': 'No URL available'}), 404
        return jsonify(shared_store._store)
