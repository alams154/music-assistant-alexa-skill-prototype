from flask import Blueprint, Response, current_app, request, redirect, url_for
from markupsafe import escape
from pathlib import Path
from datetime import datetime

from skill import device_mapping

devices_bp = Blueprint('devices_bp', __name__)


def _extract_device_id(payload):
    try:
        return (
            payload.get('context', {})
            .get('System', {})
            .get('device', {})
            .get('deviceId')
        )
    except Exception:
        return None


def _extract_intent_name(payload):
    try:
        req = payload.get('request', {})
        intent = req.get('intent')
        if isinstance(intent, dict):
            return intent.get('name')
        return req.get('type')
    except Exception:
        return None


def _seen_devices():
    """Return {device_id: {'last_seen': ts, 'last_request': name}} from intent logs."""
    intent_logs = current_app.config.get('INTENT_LOGS', [])
    seen = {}
    for entry in intent_logs:
        payload = entry.get('incoming')
        if not isinstance(payload, dict):
            continue
        device_id = _extract_device_id(payload)
        if not device_id:
            continue
        ts = entry.get('ts')
        name = _extract_intent_name(payload)
        prev = seen.get(device_id)
        if prev is None or (ts and (prev.get('last_seen') or 0) <= ts):
            seen[device_id] = {'last_seen': ts, 'last_request': name}
    return seen


def _format_ts(ts):
    if not ts:
        return '(unknown)'
    try:
        return datetime.fromtimestamp(float(ts)).strftime('%H:%M:%S %Y-%m-%d')
    except Exception:
        return str(ts)


@devices_bp.route('/devices', methods=['GET'])
def devices_page():
    mapping = device_mapping.load_mapping()
    seen = _seen_devices()

    all_device_ids = sorted(set(mapping.keys()) | set(seen.keys()),
                             key=lambda d: -(seen.get(d, {}).get('last_seen') or 0))

    rows = []
    for device_id in all_device_ids:
        info = seen.get(device_id, {})
        current_player = mapping.get(device_id, '')
        rows.append(f"""
        <tr>
            <td><code title="{escape(device_id)}">{escape(device_id[-12:])}</code></td>
            <td>{escape(_format_ts(info.get('last_seen')))}</td>
            <td>{escape(info.get('last_request') or '(not seen this session)')}</td>
            <td>
                <form method="POST" action="/devices" class="mapping-form">
                    <input type="hidden" name="device_id" value="{escape(device_id)}">
                    <input type="text" name="player_id" value="{escape(current_player)}"
                           placeholder="MA player_id (e.g. Studio)">
                    <button type="submit">Save</button>
                </form>
            </td>
        </tr>""")

    rows_html = '\n'.join(rows) or '<tr><td colspan="4" class="muted">No devices seen yet. Trigger an intent from each Echo, then reload this page.</td></tr>'

    body = f"""
    <p class="muted">Alexa does not expose a friendly device name to Custom Skills, only an opaque per-device id.
    Trigger any voice command (e.g. "next") from each Echo you want to control MA from, reload this page,
    then pair each device id with its Music Assistant player_id (the name shown in MA, e.g. "Studio").
    Only Next/Previous are currently routed to MA.</p>
    <table>
        <thead><tr><th>Device id (last 12 chars)</th><th>Last seen</th><th>Last request</th><th>MA player_id</th></tr></thead>
        <tbody>
        {rows_html}
        </tbody>
    </table>
    """

    try:
        tpl_path = Path(__file__).parent.parent / 'templates' / 'devices.html'
        tpl = tpl_path.read_text()
        tpl = tpl.replace('__DEVICES_BODY__', body)
        return Response(tpl, status=200, mimetype='text/html')
    except Exception:
        html = f"<!doctype html><html><head><meta charset='utf-8'><title>Device Mapping</title></head><body><h1>Device Mapping</h1>{body}</body></html>"
        return Response(html, status=200, mimetype='text/html')


@devices_bp.route('/devices', methods=['POST'])
def devices_save():
    device_id = (request.form.get('device_id') or '').strip()
    player_id = (request.form.get('player_id') or '').strip()
    if device_id:
        device_mapping.set_player_for_device(device_id, player_id or None)
    return redirect(url_for('devices_bp.devices_page'))
