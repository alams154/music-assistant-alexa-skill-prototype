from flask import Blueprint, Response, jsonify, request, current_app
from pathlib import Path
import json
import os
from copy import deepcopy
import requests
import urllib.parse

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
    page = tpl_path.read_text()
    # expose configured SKILL_HOSTNAME to the client for convenience
    page = page.replace('__SKILL_HOSTNAME__', json.dumps(os.environ.get('SKILL_HOSTNAME', '')))
    return Response(page, mimetype='text/html')


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


def _resolve_doh(hostname):
    """Resolve hostname using DNS-over-HTTPS (Cloudflare) to bypass local /etc/hosts."""
    try:
        # Use Cloudflare DoH JSON endpoint
        resp = requests.get('https://cloudflare-dns.com/dns-query', params={'name': hostname, 'type': 'A'}, headers={'Accept': 'application/dns-json'}, timeout=5)
        if resp.ok:
            j = resp.json()
            answers = j.get('Answer') or []
            for a in answers:
                # Answer entries may contain 'data' with IP or CNAMEs
                ip = a.get('data')
                if ip and isinstance(ip, str):
                    return ip
    except Exception:
        pass
    return None


@simulator_bp.route('/simulator/send', methods=['POST'])
def simulator_send():
    """Send a constructed Alexa IntentRequest to the skill and return response.

    Request JSON fields:
    - intent: intent name (required)
    - use: 'local' or 'hostname' (default 'local')
    - sample: optional sample utterance (unused, kept for future)
    """
    data = request.get_json(silent=True) or {}
    intent = data.get('intent')
    use = data.get('use', 'local')
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

    # Determine target URL
    target_url = None
    headers = {'Content-Type': 'application/json'}
    auth = None
    try:
        from env_secrets import get_env_secret
        app_user = get_env_secret('APP_USERNAME')
        app_pass = get_env_secret('APP_PASSWORD')
        if app_user and app_pass:
            auth = (app_user, app_pass)
    except Exception:
        auth = None

    if use == 'hostname':
        raw = os.environ.get('SKILL_HOSTNAME', '').strip()
        if not raw:
            return jsonify({'error': 'SKILL_HOSTNAME not configured'}), 400
        # normalize scheme
        if raw.startswith('http://') or raw.startswith('https://'):
            parsed = urllib.parse.urlparse(raw)
            scheme = parsed.scheme
            host = parsed.hostname
            port = parsed.port
        else:
            scheme = 'https'
            host = raw
            port = None

        ip = _resolve_doh(host)
        if not ip:
            return jsonify({'error': 'DNS resolution failed for host: ' + host}), 500

        # build URL using resolved IP; include port if present
        netloc = ip
        if port:
            netloc = f"{ip}:{port}"
        target_url = f"{scheme}://{netloc}/"
        # set Host header to original hostname so virtual hosts work
        headers['Host'] = host
        # we will disable certificate verification because IP won't match cert
        verify = False
    else:
        # local: post to this server's root
        target_url = request.host_url.rstrip('/') + '/'
        verify = True

    # Provide minimal Alexa signature headers so the ask-sdk verifier doesn't
    # immediately raise "Missing Signature/Certificate for the skill request".
    # These are dummy values intended for local testing only; the verifier may
    # still perform full signature validation depending on configuration.
    headers.setdefault('Signature', 'dummy-signature')
    headers.setdefault('SignatureCertChainUrl', 'https://s3.amazonaws.com/echo.api/echo-api-cert.pem')
    # Also send simulator-specific shadow headers which the app will copy into
    # the WSGI environ if the real headers are absent (helps when proxies or
    # local networking strip uncommon header names).
    headers.setdefault('X-Simulator-Signature', 'dummy-signature')
    headers.setdefault('X-Simulator-CertUrl', 'https://s3.amazonaws.com/echo.api/echo-api-cert.pem')

    try:
        resp = requests.post(target_url, json=payload, headers=headers, auth=auth, timeout=10, verify=verify)
        # return response status + body (text)
        try:
            body = resp.content.decode('utf-8', errors='replace')
        except Exception:
            body = str(resp.content)
        return jsonify({'status_code': resp.status_code, 'body': body})
    except requests.exceptions.SSLError as e:
        # SSL handshake failed when connecting to resolved IP. Retry by
        # posting to the original hostname (this sets correct SNI). This
        # is a best-effort fallback for local testing.
        try:
            if use == 'hostname' and 'host' in locals():
                alt_url = f"{scheme}://{host}/"
                try:
                    resp = requests.post(alt_url, json=payload, headers=headers, auth=auth, timeout=10, verify=True)
                    try:
                        body = resp.content.decode('utf-8', errors='replace')
                    except Exception:
                        body = str(resp.content)
                    return jsonify({'status_code': resp.status_code, 'body': body, 'note': 'retried using hostname for SNI'})
                except Exception:
                    pass
        except Exception:
            pass
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500
