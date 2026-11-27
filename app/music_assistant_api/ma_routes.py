"""Route definitions for music_assistant_api (ma_routes)."""

from flask import jsonify, request
import os
import time
from urllib.parse import urlparse, urlunparse
import shared_store
import logging as _logging
_ma_log = _logging.getLogger('ma_routes')


def _rewrite_url(url: str) -> str:
    """Rewrite internal Music Assistant URLs to public hostname."""
    if not url:
        return url
    ma_hostname = os.environ.get('MA_HOSTNAME', '').strip()
    if not ma_hostname:
        return url
    try:
        parsed = urlparse(url)
        if not parsed.hostname:
            return url
        rewritten = urlunparse((
            'https', ma_hostname, parsed.path,
            parsed.params, parsed.query, parsed.fragment
        ))
        return rewritten
    except Exception:
        return url


def register_routes(bp):
    # each HTTP request starts without a player (threads are reused)
    bp.before_request(lambda: shared_store.set_request_player(None))

    @bp.route('/push-url', methods=['POST'])
    def push_url():
        data = request.get_json(silent=True) or {}
        shared_store.set_request_player(data.get('playerId'))   # MA 2.11
        stream_url = data.get('streamUrl')
        if not stream_url:
            return jsonify({'error': 'Missing required fields'}), 400

        stream_url = _rewrite_url(stream_url)
        image_url = _rewrite_url(data.get('imageUrl'))

        _prev = shared_store._store or {}
        _same_stream = bool(_prev.get('streamAt')) and shared_store.stream_key(
            _prev.get('streamUrl')) == shared_store.stream_key(stream_url)
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
        # when this stream was pushed, and its first title (a metadata upload keeps the stream)
        shared_store._store['streamAt'] = _prev['streamAt'] if _same_stream else time.time()
        shared_store._store['streamTitle'] = _prev.get('streamTitle') if _same_stream else data.get('title')
        # MA 2.11 sends playerId + canSkipSpeech and skips the
        # voice relaunch when we answer pageLive: true.
        answer = {'status': 'ok', 'version': shared_store._version}
        player_id = data.get('playerId')
        if player_id:
            live = bool(data.get('canSkipSpeech')) and shared_store.page_live(player_id)
            if live and shared_store.stream_key(stream_url) != shared_store.stream_key(
                    shared_store._rendered_stream.get(player_id)):
                shared_store.add_pending(player_id, 'stream')
            answer['pageLive'] = live
            _ma_log.info("push-url %s: pageLive=%s (%s)", player_id, live,
                         (data.get('title') or '')[:40])
        return jsonify(answer)

    @bp.route('/control', methods=['POST'])
    def control():
        # Pause/resume for the open APL screen.
        data = request.get_json(silent=True) or {}
        player_id = data.get('playerId')
        command = data.get('command')
        if command not in ('pause', 'resume'):
            return jsonify({'error': 'Unsupported command', 'pageLive': False}), 400
        live = bool(data.get('canSkipSpeech')) and shared_store.page_live(player_id)
        if live:
            shared_store.add_pending(player_id, command)
        _ma_log.info("control %s %s: pageLive=%s", player_id, command, live)
        return jsonify({'pageLive': live})

    @bp.route('/latest-url', methods=['GET'])
    def latest_url():
        if not shared_store._store:
            return jsonify({'error': 'No URL available'}), 404
        return jsonify(shared_store._store)
