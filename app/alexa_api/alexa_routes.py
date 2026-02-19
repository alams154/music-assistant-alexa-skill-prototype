"""Route definitions for alexa_api (alexa_routes).

This module registers HTTP endpoints on a provided Flask
`Blueprint`. It stores the last posted Alexa event in a
module-level `_store` variable and exposes a simple status and
retrieval endpoints similar to `ma_routes`.
"""

import os
import json
from pathlib import Path
from flask import jsonify, request


_store = None


def register_routes(bp):
    @bp.route('/push-url', methods=['POST'])
    def push_url():
        """Accept JSON with streamUrl and optional metadata and store it.

        Expected JSON body: { streamUrl, title, secondary, imageUrl }
        """
        global _store
        data = request.get_json(silent=True) or {}
        stream_url = data.get('streamUrl')
        if not stream_url:
            return jsonify({'error': 'Missing required fields'}), 400

        _store = {
            'streamUrl': stream_url,
            'title': data.get('title'),
            'secondary': data.get('secondary'),
            'imageUrl': data.get('imageUrl'),
        }
        return jsonify({'status': 'ok'})

    @bp.route('/latest-url', methods=['GET'])
    def latest_url():
        """Return the last pushed stream metadata from the Alexa skill.
        """
        if not _store:
            return jsonify({'error': 'Check skill invocations and skill logs.  If there are no invocations, you have made a configuration error'}), 404
        return jsonify(_store)
    
    @bp.route('/intents', methods=['GET'])
    def intents():
        """Return the list of built-in supported Alexa intents, locale specific"""
        # Get the locale from environment variable, default to en-US
        locale = os.environ.get('LOCALE', 'en-US')
        
        # Build path to the locale-specific intents file
        intents_file = Path(__file__).parent.parent / 'models' / 'built-in' / f'{locale}.json'
        
        # Load intents from the JSON file
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
