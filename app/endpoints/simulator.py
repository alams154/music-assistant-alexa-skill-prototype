from flask import Blueprint, Response, jsonify, request, current_app
from pathlib import Path
import json
import os
from copy import deepcopy
from ask_sdk_model import RequestEnvelope

simulator_bp = Blueprint('simulator_bp', __name__)


# Internal sample payload used by the simulator UI. This avoids reading
# repository-local payload.json files and prevents leaking account data.
SAMPLE_PAYLOAD = {
    'version': '1.0',
    'session': {
        'new': True,
        'sessionId': 'SessionId.simulator',
        'application': {'applicationId': ''},
        'user': {'userId': 'amzn1.ask.account.simulator'}
    },
    'context': {
        'System': {
            'apiAccessToken': '',
            'application': {'applicationId': ''},
            'device': {'deviceId': 'amzn1.ask.device.simulator'}
        },
        'Advertising': {'advertisingId': ''}
    },
    'request': {
        'type': 'IntentRequest',
        'requestId': 'EdwRequestId.simulator',
        'locale': 'en-US',
        'timestamp': '2020-01-01T00:00:00Z',
        'intent': {'name': '', 'slots': {}}
    }
}


@simulator_bp.route('/simulator', methods=['GET'])
def simulator_index():
    tpl_path = Path(__file__).parent.parent / 'templates' / 'simulator.html'
    return Response(tpl_path.read_text(), mimetype='text/html')


def _load_model_intents():
    # Prefer en-US model; fall back to first model file if missing
    try:
        model_path = Path(__file__).parent.parent / 'models' / 'en-US.json'
        if not model_path.exists():
            # try scanning models dir
            mdir = Path(__file__).parent.parent / 'models'
            for p in mdir.glob('*.json'):
                model_path = p
                break
        data = json.loads(model_path.read_text())
        intents = data.get('interactionModel', {}).get('languageModel', {}).get('intents', [])
        intents_out = []
        for it in intents:
            intents_out.append({'name': it.get('name'), 'samples': it.get('samples', [])})
        return intents_out
    except Exception:
        return []


@simulator_bp.route('/simulator/api', methods=['GET'])
def simulator_api():
    """Return available intents and server-side config for the simulator UI."""
    intents = _load_model_intents()
    return jsonify({'intents': intents, 'skill_hostname': os.environ.get('SKILL_HOSTNAME', '')})


@simulator_bp.route('/simulator/payload', methods=['GET'])
def simulator_payload():
    """Return the default constructed Alexa IntentRequest payload for an intent."""
    intent = request.args.get('intent')
    if not intent:
        return jsonify({'error': 'missing intent parameter'}), 400
    # Use the internal SAMPLE_PAYLOAD to avoid reading repo-local files
    payload = deepcopy(SAMPLE_PAYLOAD)
    # set the requested intent name and ensure slots exist
    payload['request']['intent']['name'] = intent
    payload['request']['intent'].setdefault('slots', {})
    return jsonify(payload)


@simulator_bp.route('/simulator/send', methods=['POST'])
def simulator_send():
    """Send a constructed Alexa IntentRequest to the skill and return response.

    Request JSON fields:
    - intent: intent name (required)
    - sample: optional sample utterance (unused, kept for future)
    """
    data = request.get_json(silent=True) or {}
    intent = data.get('intent')
    sample = data.get('sample')
    if not intent:
        return jsonify({'error': 'missing intent'}), 400

    # build minimal Alexa intent request envelope (unless override provided)
    override = data.get('override_payload')
    if override:
        try:
            if isinstance(override, str):
                payload = json.loads(override)
            else:
                payload = override
        except Exception as e:
            return jsonify({'error': f'invalid override_payload JSON: {e}'}), 400
    else:
        payload = {
            'version': '1.0',
            'session': {
                'new': True,
                'sessionId': 'SessionId.simulator',
                'application': {'applicationId': ''},
                'user': {'userId': 'amzn1.ask.account.simulator'}
            },
            'context': {},
            'request': {
                'type': 'IntentRequest',
                'requestId': 'EdwRequestId.simulator',
                'locale': 'en-US',
                'timestamp': '2020-01-01T00:00:00Z',
                'intent': {'name': intent, 'slots': {}}
            }
        }

    # Run it in the app: the skill endpoint only takes requests signed by
    # Amazon. This page is behind the web UI's password, like setup and /ma.
    skill = current_app.config['ALEXA_SKILL']
    # ask-sdk checks the skill ID against the request's context.
    system = payload.setdefault('context', {}).setdefault('System', {})
    for where in (payload.get('session'), system):
        if isinstance(where, dict):
            where.setdefault('application', {})['applicationId'] = skill.skill_id or ''
    try:
        envelope = skill.serializer.deserialize(json.dumps(payload), RequestEnvelope)
        response = skill.invoke(request_envelope=envelope, context=None)
        return jsonify({'status_code': 200, 'body': json.dumps(skill.serializer.serialize(response))})
    except Exception as e:
        current_app.logger.exception('Simulator request failed')
        return jsonify({'status_code': 500, 'body': str(e)})
