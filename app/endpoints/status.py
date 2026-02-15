from flask import Blueprint, request, jsonify, Response, current_app
from markupsafe import escape
import json
import os
import re
import shutil
import subprocess
import urllib.parse

import requests
from requests.exceptions import RequestException
from env_secrets import get_env_secret
from pathlib import Path

status_bp = Blueprint('status_bp', __name__)


def _build_status_json():
    api_user = get_env_secret('APP_USERNAME')
    api_pass = get_env_secret('APP_PASSWORD')
    skill_html = '<span class="led green"></span> Skill running'

    skill_ask_html = '<span class="muted">ASK CLI check unavailable</span>'
    try:
        skill_host = os.environ.get('SKILL_HOSTNAME', '').strip()
        if shutil.which('ask') and skill_host:
            ls = subprocess.run(['ask', 'smapi', 'list-skills-for-vendor', '--profile', 'default'], capture_output=True, text=True)
            out = ls.stdout or ls.stderr or ''
            m = re.search(r'amzn1\.ask\.skill\.[0-9a-fA-F\-]+', out)
            if not m:
                skill_ask_html = '<span class="led red"></span> Music Assistant Skill interaction model not found via ASK CLI'
            else:
                sid = m.group(0)
                mf = subprocess.run(['ask', 'smapi', 'get-skill-manifest', '--skill-id', sid, '--profile', 'default'], capture_output=True, text=True)
                mf_out = mf.stdout or mf.stderr or ''
                mm = re.search(r'https?://[^"\s\)\]]+', mf_out)
                try:
                    if skill_host.startswith('http://') or skill_host.startswith('https://'):
                        cfg_host = urllib.parse.urlparse(skill_host).netloc
                    else:
                        cfg_host = skill_host
                except Exception:
                    cfg_host = skill_host

                testing_enabled = False
                try:
                    en = subprocess.run(['ask', 'smapi', 'get-skill-enablement-status', '--skill-id', sid, '--stage', 'development', '--profile', 'default'], capture_output=True, text=True)
                    en_out = en.stdout or en.stderr or ''
                    if en.returncode == 0 or 'Command executed successfully' in en_out:
                        testing_enabled = True
                    else:
                        if re.search(r'\[Error\]:\s*\{', en_out) or re.search(r'404', en_out):
                            testing_enabled = False
                        elif re.search(r'"isEnabled"\s*:\s*true', en_out, re.IGNORECASE) or re.search(r'"enabled"\s*:\s*true', en_out, re.IGNORECASE):
                            testing_enabled = True
                except Exception:
                    testing_enabled = False

                is_green = False
                if not mm:
                    testing_msg = 'testing enabled' if testing_enabled else 'testing not enabled'
                    skill_ask_html = f'<span class="led yellow"></span> Music Assistant Skill interaction model {escape(sid)} found; endpoint not set ({testing_msg})'
                else:
                    uri = mm.group(0)
                    try:
                        parsed = urllib.parse.urlparse(uri)
                        manifest_host = parsed.netloc
                        locale_list = []
                        try:
                            mf_json = None
                            try:
                                mf_json = json.loads(mf_out)
                            except Exception:
                                idx = mf_out.find('{')
                                if idx != -1:
                                    try:
                                        mf_json = json.loads(mf_out[idx:])
                                    except Exception:
                                        mf_json = None
                            if mf_json:
                                locales_obj = mf_json.get('manifest', {}).get('publishingInformation', {}).get('locales', {})
                                if isinstance(locales_obj, dict):
                                    locale_list = list(locales_obj.keys())
                        except Exception:
                            locale_list = []

                        locale_display = ','.join(locale_list) if locale_list else 'unknown'

                        if manifest_host == cfg_host:
                            if testing_enabled:
                                skill_ask_html = f'<span class="led green"></span> Music Assistant Skill interaction model found; endpoint matches ({escape(manifest_host)}); testing enabled; locale: {escape(locale_display)}'
                                is_green = True
                            else:
                                skill_ask_html = f'<span class="led yellow"></span> Music Assistant Skill interaction model found and endpoint matches ({escape(manifest_host)}); testing NOT enabled'
                        else:
                            testing_note = 'testing enabled' if testing_enabled else 'testing not enabled'
                            skill_ask_html = f'<span class="led red"></span> Music Assistant Skill interaction model endpoint mismatch (manifest: {escape(manifest_host)} vs configured: {escape(cfg_host)}); {testing_note}'
                    except Exception:
                        testing_msg = 'testing enabled' if testing_enabled else 'testing not enabled'
                        skill_ask_html = f'<span class="led yellow"></span> Music Assistant Skill interaction model found; endpoint parse failed ({testing_msg})'

                try:
                    if not is_green:
                        skill_ask_html += ' <button onclick="window.location=\'/setup\'" style="margin-left:8px">Open Setup</button>'
                except Exception:
                    pass
        else:
            if not shutil.which('ask'):
                skill_ask_html = '<span class="muted">ask CLI not available in container</span>'
            else:
                skill_ask_html = '<span class="muted">SKILL_HOSTNAME not configured</span>'
    except Exception as e:
        skill_ask_html = f'<span class="muted">ASK check error: {escape(str(e))}</span>'

    # MA API check
    endpoint_url = request.host_url.rstrip('/') + '/ma/latest-url'
    try:
        auth = (api_user, api_pass) if api_user and api_pass else None
        resp = requests.get(endpoint_url, timeout=2, auth=auth)
        try:
            content_text = resp.content.decode('utf-8', errors='replace')
        except Exception:
            content_text = str(resp.content)
        try:
            parsed = json.loads(content_text)
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
            content_preview = escape(pretty)
        except Exception:
            content_preview = escape(content_text)
        if len(content_preview) > 500:
            content_preview = content_preview[:500] + '...'
        if resp.ok:
            ma_api_html = (
                f'<span class="led green"></span> Music Assistant API reachable ({resp.status_code}) — /ma/latest-url'
                f"<pre style='white-space:pre-wrap;background:#f6f6f6;padding:8px;border-radius:4px;max-height:200px;overflow:auto'>"
                f"{content_preview}</pre>"
            )
        else:
            ma_api_html = (
                f'<span class="led red"></span> Music Assistant API responded {resp.status_code} for /ma/latest-url'
                f"<pre style='white-space:pre-wrap;background:#fdf2f2;padding:8px;border-radius:4px;max-height:200px;overflow:auto'>"
                f"{content_preview}</pre>"
            )
    except RequestException as e:
        ma_api_html = f'<span class="led red"></span> Error: {str(e)}'

    # Alexa API check
    alexa_endpoint = request.host_url.rstrip('/') + '/alexa/latest-url'
    try:
        auth = (api_user, api_pass) if api_user and api_pass else None
        resp = requests.get(alexa_endpoint, timeout=2, auth=auth)
        try:
            content_text = resp.content.decode('utf-8', errors='replace')
        except Exception:
            content_text = str(resp.content)
        try:
            parsed = json.loads(content_text)
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
            content_preview = escape(pretty)
        except Exception:
            content_preview = escape(content_text)
        if len(content_preview) > 500:
            content_preview = content_preview[:500] + '...'
        if resp.ok:
            alexa_api_html = (
                f'<span class="led green"></span> Alexa API reachable ({resp.status_code}) — /alexa/latest-url'
                f"<pre style='white-space:pre-wrap;background:#f6f6f6;padding:8px;border-radius:4px;max-height:200px;overflow:auto'>"
                f"{content_preview}</pre>"
            )
        else:
            alexa_api_html = (
                f'<span class="led red"></span> Alexa API responded {resp.status_code} for /alexa/latest-url'
                f"<pre style='white-space:pre-wrap;background:#fdf2f2;padding:8px;border-radius:4px;max-height:200px;overflow:auto'>"
                f"{content_preview}</pre>"
            )
    except RequestException as e:
        alexa_api_html = f'<span class="led red"></span> Error: {str(e)}'

    # lightweight invocations link
    intent_logs = current_app.config.get('INTENT_LOGS', [])
    count = len(intent_logs) if intent_logs else 0
    if count:
        simulator_html = f'<a href="/invocations" target="_blank" rel="noopener noreferrer">View {count} invocations</a>'
    else:
        simulator_html = '<span class="muted">No recent invocations</span>'

    return {'skill_html': skill_html, 'skill_ask_html': skill_ask_html, 'ma_api_html': ma_api_html, 'alexa_api_html': alexa_api_html, 'simulator_html': simulator_html, 'created': False}


def _compute_ma_api_html(api_user=None, api_pass=None):
    api_user = api_user or get_env_secret('APP_USERNAME')
    api_pass = api_pass or get_env_secret('APP_PASSWORD')
    endpoint_url = (request.host_url.rstrip('/') if request else '') + '/ma/latest-url'
    try:
        auth = (api_user, api_pass) if api_user and api_pass else None
        resp = requests.get(endpoint_url, timeout=2, auth=auth)
        try:
            content_text = resp.content.decode('utf-8', errors='replace')
        except Exception:
            content_text = str(resp.content)
        try:
            parsed = json.loads(content_text)
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
            content_preview = escape(pretty)
        except Exception:
            content_preview = escape(content_text)
        if len(content_preview) > 500:
            content_preview = content_preview[:500] + '...'
        if resp.ok:
            return (
                f'<span class="led green"></span> Music Assistant API reachable ({resp.status_code}) — /ma/latest-url'
                f"<pre style='white-space:pre-wrap;background:#f6f6f6;padding:8px;border-radius:4px;max-height:200px;overflow:auto'>"
                f"{content_preview}</pre>"
            )
        else:
            return (
                f'<span class="led red"></span> Music Assistant API responded {resp.status_code} for /ma/latest-url'
                f"<pre style='white-space:pre-wrap;background:#fdf2f2;padding:8px;border-radius:4px;max-height:200px;overflow:auto'>"
                f"{content_preview}</pre>"
            )
    except RequestException as e:
        return f'<span class="led red"></span> Error: {str(e)}'


def _compute_alexa_api_html(api_user=None, api_pass=None):
    api_user = api_user or get_env_secret('APP_USERNAME')
    api_pass = api_pass or get_env_secret('APP_PASSWORD')
    alexa_endpoint = (request.host_url.rstrip('/') if request else '') + '/alexa/latest-url'
    try:
        auth = (api_user, api_pass) if api_user and api_pass else None
        resp = requests.get(alexa_endpoint, timeout=2, auth=auth)
        try:
            content_text = resp.content.decode('utf-8', errors='replace')
        except Exception:
            content_text = str(resp.content)
        try:
            parsed = json.loads(content_text)
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
            content_preview = escape(pretty)
        except Exception:
            content_preview = escape(content_text)
        if len(content_preview) > 500:
            content_preview = content_preview[:500] + '...'
        if resp.ok:
            return (
                f'<span class="led green"></span> Alexa API reachable ({resp.status_code}) — /alexa/latest-url'
                f"<pre style='white-space:pre-wrap;background:#f6f6f6;padding:8px;border-radius:4px;max-height:200px;overflow:auto'>"
                f"{content_preview}</pre>"
            )
        else:
            return (
                f'<span class="led red"></span> Alexa API responded {resp.status_code} for /alexa/latest-url'
                f"<pre style='white-space:pre-wrap;background:#fdf2f2;padding:8px;border-radius:4px;max-height:200px;overflow:auto'>"
                f"{content_preview}</pre>"
            )
    except RequestException as e:
        return f'<span class="led red"></span> Error: {str(e)}'


@status_bp.route('/status/ma', methods=['GET'])
def status_ma():
    return jsonify({'ma_api_html': _compute_ma_api_html()})


@status_bp.route('/status/alexa', methods=['GET'])
def status_alexa():
    return jsonify({'alexa_api_html': _compute_alexa_api_html()})

@status_bp.route('/status', methods=['GET'])
def status():
    # If client requested JSON, return the aggregated checks
    want_json = request.args.get('format') == 'json' or 'application/json' in (request.headers.get('Accept') or '')
    if want_json:
        return jsonify(_build_status_json())

    # Non-JSON: render status template
    try:
        tpl_path = Path(__file__).parent.parent / 'templates' / 'status.html'
        tpl = tpl_path.read_text()
        tpl = tpl.replace('__SKILL_HTML__', '<span class="led green"></span> Skill running')
        tpl = tpl.replace('__SKILL_ASK_HTML__', '<span class="muted">Checking ASK CLI status...</span>')
        tpl = tpl.replace('__MA_API_HTML__', '<span class="muted">Checking Music Assistant API...</span>')
        tpl = tpl.replace('__ALEXA_API_HTML__', '<span class="muted">Checking Alexa API...</span>')
        intent_logs = current_app.config.get('INTENT_LOGS', [])
        count = len(intent_logs) if intent_logs else 0
        if count:
            simulator_html = f'<a href="/invocations" target="_blank" rel="noopener noreferrer">View {count} invocations</a>'
        else:
            simulator_html = '<span class="muted">No recent invocations</span>'
        tpl = tpl.replace('__SIMULATOR_HTML__', simulator_html)
        return Response(tpl, status=200, mimetype='text/html')
    except Exception:
        html = """<!doctype html>
            <html>
            <head><meta charset="utf-8"><title>Service Status</title></head>
            <body>
                <h1>Service Status</h1>
                <div><span class=\"led green\"></span> Skill running</div>
                <div><span class=\"muted\">Checking ASK CLI status...</span></div>
                <div><span class=\"muted\">Checking Music Assistant API...</span></div>
            </body>
            </html>"""
        return Response(html, status=200, mimetype='text/html')


@status_bp.route('/status/api', methods=['GET'])
def status_api():
    """Lightweight API used by the status UI to fetch aggregated checks."""
    return jsonify(_build_status_json())


@status_bp.route('/status/ask', methods=['GET'])
def status_ask():
    """Return only the ASK CLI check fragment used by the client UI."""
    data = _build_status_json()
    return jsonify({'skill_ask_html': data.get('skill_ask_html')})


@status_bp.route('/status/invocations', methods=['GET'])
def status_invocations():
    """Return the current invocation count and simulator HTML so the UI can refresh it live."""
    intent_logs = current_app.config.get('INTENT_LOGS', [])
    count = len(intent_logs) if intent_logs else 0
    if count:
        simulator_html = f'<a href="/invocations" target="_blank" rel="noopener noreferrer">View {count} invocations</a>'
    else:
        simulator_html = '<span class="muted">No recent invocations</span>'
    return jsonify({'count': count, 'simulator_html': simulator_html})
