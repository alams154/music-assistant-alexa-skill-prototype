"""Route definitions for alexa_api (alexa_routes)."""

import os
import json
from pathlib import Path
from flask import jsonify, request
import shared_store


def register_routes(bp):
    bp.before_request(lambda: shared_store.set_request_player(None))

    @bp.route('/push-url', methods=['POST'])
    def push_url():
        data = request.get_json(silent=True) or {}
        shared_store.set_request_player(data.get('playerId'))
        stream_url = data.get('streamUrl')
        if not stream_url:
            return jsonify({'error': 'Missing required fields'}), 400

        shared_store._store = {
            'streamUrl': stream_url,
            'title': data.get('title'),
            'secondary': data.get('secondary'),
            'imageUrl': data.get('imageUrl'),
        }
        return jsonify({'status': 'ok'})

    @bp.route('/playback-state', methods=['GET'])
    def playback_state():
        # What the Echo last reported, for MA's position correction.
        import time as _time
        player_id = request.args.get('player_id')
        shared_store.set_request_player(player_id)
        report = shared_store.get_report(player_id)
        if not report:
            return jsonify({})
        latest = (shared_store._store or {}).get('streamUrl')
        activity = report['activity']
        if activity == 'PLAYING' and not shared_store.page_live(player_id):
            activity = 'STOPPED'
        return jsonify({
            'current': bool(latest) and shared_store.stream_key(report.get('streamUrl'))
                       == shared_store.stream_key(latest),
            'activity': activity,
            'offsetMs': report['offsetMs'],
            'ageSeconds': max(0.0, _time.time() - report['observedAt']),
            'observedAt': report['observedAt'],
        })

    @bp.route('/latest-url', methods=['GET'])
    def latest_url():
        if not shared_store._store:
            return jsonify({'error': 'Check skill invocations and skill logs.  If there are no invocations, you have made a configuration error'}), 404
        return jsonify(shared_store._store)
    
    @bp.route('/intents', methods=['GET'])
    def intents():
        locale = os.environ.get('LOCALE', 'en-US')
        intents_file = Path(__file__).parent.parent / 'models' / 'built-in' / f'{locale}.json'
        try:
            with open(intents_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                language_model = data.get('interactionModel', {}).get('languageModel', {})
                invocation_name = language_model.get('invocationName')
                intent_list = language_model.get('intents', [])
                intents_with_utterances = [
                    {
                        'intent': intent.get('intent'),
                        'utterances': intent.get('utterances', [])
                    }
                    for intent in intent_list if intent.get('intent')
                ]
                return jsonify({
                    'locale': locale,
                    'invocationName': invocation_name,
                    'intents': intents_with_utterances
                })
        except FileNotFoundError:
            return jsonify({
                'error': f'Intents file for locale {locale} not found',
                'locale': locale,
                'invocationName': None,
                'intents': []
            }), 404
        except Exception as e:
            return jsonify({
                'error': f'Error loading intents: {str(e)}',
                'locale': locale,
                'invocationName': None,
                'intents': []
            }), 500
