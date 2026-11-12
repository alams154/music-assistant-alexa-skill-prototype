"""Route definitions for music_assistant_api (ma_routes)."""

import logging
from flask import jsonify, request
import shared_store


def register_routes(bp):
    @bp.route('/push-url', methods=['POST'])
    def push_url():
        data = request.get_json(silent=True) or {}
        stream_url = data.get('streamUrl')
        if not stream_url:
            return jsonify({'error': 'Missing required fields'}), 400

        image_url = data.get('imageUrl')
        version, player_key = shared_store.put_ma_stream(
            stream_url=stream_url,
            title=data.get('title'),
            artist=data.get('artist'),
            album=data.get('album'),
            image_url=image_url,
        )
        logging.getLogger('app').info(
            'MA push-url v%s: player=%r title=%r has_image=%s',
            version,
            player_key,
            data.get('title'),
            bool(image_url),
        )
        return jsonify({'status': 'ok', 'version': version, 'playerKey': player_key})

    @bp.route('/latest-url', methods=['GET'])
    def latest_url():
        if not shared_store._store:
            return jsonify({'error': 'No URL available'}), 404
        return jsonify(shared_store._store)
