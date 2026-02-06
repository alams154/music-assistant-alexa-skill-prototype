import os
from flask import Flask, request, jsonify, Response
from markupsafe import escape
from flask_ask_sdk.skill_adapter import SkillAdapter
from lambda_function import sb  # sb is the SkillBuilder from lambda_function.py
import requests
import json
from requests.exceptions import RequestException
import music_assistant_alexa_api as maa_api
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.middleware.proxy_fix import ProxyFix
from env_secrets import get_env_secret
import swagger_ui as maa_swagger
from collections import deque
import threading
import subprocess
from pathlib import Path
import time
import pty
import re
import shutil
import urllib.parse
import base64


from setup_helpers import sanitize_log, enqueue_setup_log, setup_reader_thread as _helpers_setup_reader_thread, read_master_loop as _helpers_read_master_loop
from signal_helpers import register_signal_handlers

app = Flask(__name__)
# Allow overriding where ASK CLI stores credentials so they persist across containers.
# If ASK_CREDENTIALS_DIR is set (e.g. /root/.ask) set HOME to its parent so tools
# that rely on ~/.ask (ASK CLI) use the mounted location.
try:
    # If the persistent credentials volume is mounted at /root/.ask inside the
    # container, set HOME to /root so ASK CLI and related tools use ~/.ask there.
    if Path('/root/.ask').exists():
        os.environ['HOME'] = '/root'
        app.logger.info('Using persistent ASK credentials at /root/.ask')
except Exception:
    pass
skill_adapter = SkillAdapter(
    skill=sb.create(),
    skill_id="",
    app=app)

# Mount the Music Assistant Alexa API (only ma routes will be mounted at /ma)
ma_app = maa_api.create_ma_app()


class BasicAuthMiddleware:
    """WSGI middleware that enforces HTTP Basic auth using APP_USERNAME/APP_PASSWORD.

    Applied to the `ma_app` WSGI app so requests to `/ma` require the same
    APP_USERNAME/APP_PASSWORD credentials as the rest of the app. If no
    APP_USERNAME/APP_PASSWORD are configured, auth is not enforced.
    """
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        user = get_env_secret('APP_USERNAME')
        pwd = get_env_secret('APP_PASSWORD')
        if not user and not pwd:
            return self.app(environ, start_response)

        auth = environ.get('HTTP_AUTHORIZATION')
        if auth and auth.startswith('Basic '):
            try:
                token = auth.split(' ', 1)[1].strip()
                decoded = base64.b64decode(token).decode('utf-8')
                u, sep, p = decoded.partition(':')
                if sep and u == user and p == pwd:
                    return self.app(environ, start_response)
            except Exception:
                pass

        start_response('401 Unauthorized', [('Content-Type', 'text/plain'), ('WWW-Authenticate', 'Basic realm="music-assistant-skill"')])
        return [b'Access denied']

# Respect X-Forwarded-* headers when running behind a reverse proxy so
# `request.host_url` and `request.scheme` reflect the external client URL.
# Apply ProxyFix to both apps before wiring the dispatcher.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
ma_app.wsgi_app = ProxyFix(ma_app.wsgi_app, x_for=1, x_proto=1, x_host=1)
# Wrap the MA app with BasicAuthMiddleware so /ma endpoints are protected
ma_app.wsgi_app = BasicAuthMiddleware(ma_app.wsgi_app)
app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {'/ma': ma_app.wsgi_app})
app.logger.info('Mounted music-assistant-alexa-api app at /ma')


# Global basic auth for the app (protect everything except the root Alexa skill endpoint)
@app.before_request
def _check_app_basic_auth():
    # Allow the Alexa skill POST endpoint to be called without app-level auth
    if request.path == '/' and request.method == 'POST':
        return None
    # Read credentials from secrets (APP_USERNAME/APP_PASSWORD)
    app_user = get_env_secret('APP_USERNAME')
    app_pass = get_env_secret('APP_PASSWORD')
    # If no app credentials configured, do not enforce auth
    if not app_user and not app_pass:
        return None
    auth = request.authorization
    if not auth or auth.username != app_user or auth.password != app_pass:
        resp = Response('Access denied', 401)
        resp.headers['WWW-Authenticate'] = 'Basic realm="music-assistant-skill"'
        return resp

# Setup process state (separate from status page)
_setup_proc = None
_setup_logs = deque(maxlen=500)
_setup_lock = threading.Lock()

# Auth (ask configure --no-browser) process state
_setup_auth_proc = None
_setup_auth_lock = threading.Lock()
_pending_endpoint = None
_setup_auth_master_fd = None
_PENDING_FILE = Path(os.environ.get('TMPDIR', '/tmp')) / 'ask_pending_endpoint.txt'


def _enqueue_setup_log(line: str):
    # Thin wrapper to keep module-level _setup_logs while delegating logic
    enqueue_setup_log(_setup_logs, line)


# Register signal handlers via the helper module so Ctrl+C/SIGTERM are
# forwarded to spawned ask/create processes. The getter returns current
# live process references so the handler can operate on up-to-date values.
try:
    register_signal_handlers(lambda: {'_setup_auth_proc': _setup_auth_proc, '_setup_proc': _setup_proc, 'master_fd': _setup_auth_master_fd})
except Exception:
    pass


def _setup_reader_thread(proc, prefix=None):
    # Delegate implementation to helpers while binding enqueue function
    return _helpers_setup_reader_thread(proc, _enqueue_setup_log, prefix=prefix)


def _read_master_loop(master_fd, prefix=None):
    # Delegate implementation to helpers while binding enqueue function
    return _helpers_read_master_loop(master_fd, _enqueue_setup_log, prefix=prefix)


@app.route("/", methods=["POST"])
def invoke_skill():
    return skill_adapter.dispatch_request()


@app.route("/status", methods=["GET"])
def status():
    """Simple GET status page for health checks and browsing."""
    api_user = get_env_secret('APP_USERNAME')
    api_pass = get_env_secret('APP_PASSWORD')

    # Skill adapter status (we're running if this handler is invoked)
    skill_html = '<span class="led green"></span> Skill running'

    # If client requested JSON, perform full checks (may take time) and return structured data
    want_json = request.args.get('format') == 'json' or 'application/json' in (request.headers.get('Accept') or '')
    if want_json:
        # Check ASK CLI and skill status
        skill_ask_html = '<span class="muted">ASK CLI check unavailable</span>'
        try:
            skill_host = os.environ.get('SKILL_HOSTNAME', '').strip()
            if shutil.which('ask') and skill_host:
                ls = subprocess.run(['ask', 'smapi', 'list-skills-for-vendor', '--profile', 'default'], capture_output=True, text=True)
                out = ls.stdout or ls.stderr or ''
                m = re.search(r'amzn1\.ask\.skill\.[0-9a-fA-F\-]+', out)
                if not m:
                    skill_ask_html = '<span class="led red"></span> Music Assistant Skill not found via ASK CLI'
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
                        skill_ask_html = f'<span class="led yellow"></span> Music Assistant Skill {escape(sid)} found; endpoint not set ({testing_msg})'
                    else:
                        uri = mm.group(0)
                        try:
                            parsed = urllib.parse.urlparse(uri)
                            manifest_host = parsed.netloc
                            if manifest_host == cfg_host:
                                if testing_enabled:
                                    skill_ask_html = f'<span class="led green"></span> Music Assistant Skill found, endpoint matches ({escape(manifest_host)}); testing enabled'
                                    is_green = True
                                else:
                                    skill_ask_html = f'<span class="led yellow"></span> Music Assistant Skill found and endpoint matches ({escape(manifest_host)}); testing NOT enabled'
                            else:
                                testing_note = 'testing enabled' if testing_enabled else 'testing not enabled'
                                skill_ask_html = f'<span class="led red"></span> Music Assistant Skill endpoint mismatch (manifest: {escape(manifest_host)} vs configured: {escape(cfg_host)}); {testing_note}'
                        except Exception:
                            testing_msg = 'testing enabled' if testing_enabled else 'testing not enabled'
                            skill_ask_html = f'<span class="led yellow"></span> Music Assistant Skill found; endpoint parse failed ({testing_msg})'

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

        # API status: call the locally mounted /ma/latest-url endpoint on this service.
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
                api_html = (
                    f'<span class="led green"></span> API reachable ({resp.status_code}) — /ma/latest-url'
                    f"<pre style='white-space:pre-wrap;background:#f6f6f6;padding:8px;border-radius:4px;max-height:200px;overflow:auto'>"
                    f"{content_preview}</pre>"
                )
            else:
                api_html = (
                    f'<span class="led red"></span> API responded {resp.status_code} for /ma/latest-url'
                    f"<pre style='white-space:pre-wrap;background:#fdf2f2;padding:8px;border-radius:4px;max-height:200px;overflow:auto'>"
                    f"{content_preview}</pre>"
                )
        except RequestException as e:
            api_html = f'<span class="led red"></span> Error: {str(e)}'

        return jsonify({'skill_html': skill_html, 'skill_ask_html': skill_ask_html, 'api_html': api_html, 'created': False})

    # Non-JSON request: render page immediately and let client poll for updates
    try:
        tpl_path = Path(__file__).parent / 'templates' / 'status.html'
        tpl = tpl_path.read_text()
        # initial placeholders; detailed checks will be fetched by client-side polling
        tpl = tpl.replace('__SKILL_HTML__', skill_html)
        tpl = tpl.replace('__SKILL_ASK_HTML__', '<span class="muted">Checking ASK CLI status...</span>')
        tpl = tpl.replace('__API_HTML__', '<span class="muted">Checking API...</span>')
        return Response(tpl, status=200, mimetype='text/html')
    except Exception:
        html = f"""<!doctype html>
            <html>
            <head><meta charset="utf-8"><title>Service Status</title></head>
            <body>
                <h1>Service Status</h1>
                <div>{skill_html}</div>
                <div><span class=\"muted\">Checking ASK CLI status...</span></div>
                <div><span class=\"muted\">Checking API...</span></div>
            </body>
            </html>"""
        return Response(html, status=200, mimetype='text/html')


@app.route('/status/api', methods=['GET'])
def status_api():
    """Return API status fragment as JSON (fast, local API check)."""
    api_user = get_env_secret('APP_USERNAME')
    api_pass = get_env_secret('APP_PASSWORD')
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
            api_html = (
                f'<span class="led green"></span> API reachable ({resp.status_code}) — /ma/latest-url'
                f"<pre style='white-space:pre-wrap;background:#f6f6f6;padding:8px;border-radius:4px;max-height:200px;overflow:auto'>"
                f"{content_preview}</pre>"
            )
        else:
            api_html = (
                f'<span class="led red"></span> API responded {resp.status_code} for /ma/latest-url'
                f"<pre style='white-space:pre-wrap;background:#fdf2f2;padding:8px;border-radius:4px;max-height:200px;overflow:auto'>"
                f"{content_preview}</pre>"
            )
    except RequestException as e:
        api_html = f'<span class="led red"></span> Error: {str(e)}'
    return jsonify({'api_html': api_html})


@app.route('/status/ask', methods=['GET'])
def status_ask():
    """Return ASK CLI status fragment as JSON (may be slower)."""
    skill_ask_html = '<span class="muted">ASK CLI check unavailable</span>'
    try:
        skill_host = os.environ.get('SKILL_HOSTNAME', '').strip()
        if shutil.which('ask') and skill_host:
            ls = subprocess.run(['ask', 'smapi', 'list-skills-for-vendor', '--profile', 'default'], capture_output=True, text=True)
            out = ls.stdout or ls.stderr or ''
            m = re.search(r'amzn1\.ask\.skill\.[0-9a-fA-F\-]+', out)
            if not m:
                skill_ask_html = '<span class="led red"></span> Music Assistant Skill not found via ASK CLI'
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
                    skill_ask_html = f'<span class="led yellow"></span> Music Assistant Skill {escape(sid)} found; endpoint not set ({testing_msg})'
                else:
                    uri = mm.group(0)
                    try:
                        parsed = urllib.parse.urlparse(uri)
                        manifest_host = parsed.netloc
                        if manifest_host == cfg_host:
                            if testing_enabled:
                                skill_ask_html = f'<span class="led green"></span> Music Assistant Skill found, endpoint matches ({escape(manifest_host)}); testing enabled'
                                is_green = True
                            else:
                                skill_ask_html = f'<span class="led yellow"></span> Music Assistant Skill found and endpoint matches ({escape(manifest_host)}); testing NOT enabled'
                        else:
                            testing_note = 'testing enabled' if testing_enabled else 'testing not enabled'
                            skill_ask_html = f'<span class="led red"></span> Music Assistant Skill endpoint mismatch (manifest: {escape(manifest_host)} vs configured: {escape(cfg_host)}); {testing_note}'
                    except Exception:
                        testing_msg = 'testing enabled' if testing_enabled else 'testing not enabled'
                        skill_ask_html = f'<span class="led yellow"></span> Music Assistant Skill found; endpoint parse failed ({testing_msg})'

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
    return jsonify({'skill_ask_html': skill_ask_html})


# Expose OpenAPI spec and Swagger UI from the main app so docs are available
# at `/openapi.json` and `/docs` (keeps documentation separate from the API
# implementation which is mounted at `/ma`).
@app.route('/openapi.json', methods=['GET'])
def openapi_json():
    return maa_swagger.openapi_spec()


@app.route('/docs', methods=['GET'])
def docs():
    return maa_swagger.render()


@app.route('/setup', methods=['GET'])
def setup_ui():
    # Embed current logs and detected auth URL so the page shows state immediately
    initial_logs = list(_setup_logs)
    auth_url = None
    try:
        for ln in initial_logs:
            try:
                m = re.search(r"(https?://[^\s'\"]+)", ln)
                if m:
                    auth_url = m.group(1)
                    break
            except Exception:
                try:
                    if isinstance(ln, str) and ln.strip().startswith('['):
                        arr = json.loads(ln)
                        if isinstance(arr, list):
                            for item in arr:
                                mm = re.search(r"(https?://[^\s'\"]+)", str(item))
                                if mm:
                                    auth_url = mm.group(1)
                                    break
                            if auth_url:
                                break
                except Exception:
                    pass
                continue
    except Exception:
        auth_url = None

    # If persistent ASK credentials are present at /root/.ask, suppress the
    # browser-based authorization UI and do not expose an auth URL to the client.
    try:
        if Path('/root/.ask').exists():
            app.logger.info('Persistent ASK credentials found; suppressing auth UI')
            auth_url = None
    except Exception:
        pass

    # If the client requested JSON (polling), return logs + auth_url + active flag
    want_json = request.args.get('format') == 'json' or 'application/json' in (request.headers.get('Accept') or '')
    if want_json:
        active = False
        try:
            active = (_setup_proc and _setup_proc.poll() is None) or (_setup_auth_proc and _setup_auth_proc.poll() is None)
        except Exception:
            active = False
        # Return sanitized logs for the UI polling loop
        try:
            safe_logs = [sanitize_log(ln) for ln in list(_setup_logs)]
        except Exception:
            safe_logs = list(_setup_logs)
        # Detect whether the setup process has completed creation (Done. Skill ID)
        created = False
        try:
            for ln in safe_logs:
                if re.search(r'Done\.\s*Skill ID', str(ln), re.IGNORECASE):
                    created = True
                    break
        except Exception:
            created = False
        return jsonify({'logs': safe_logs, 'auth_url': auth_url, 'active': bool(active), 'created': bool(created)})

    # Load setup HTML template from disk to keep this file readable
    try:
        tpl_path = Path(__file__).parent / 'templates' / 'setup.html'
        page = tpl_path.read_text()
    except Exception:
        page = None

    # If valid ASK CLI credentials are present, show a notice on the setup page.
    try:
        creds_html = ''
        # The ASK CLI stores a cli_config under ~/.ask/cli_config when configured.
        if Path('/root/.ask/cli_config').exists():
            creds_html = '<div style="margin-top:8px;color:green;font-weight:600">Persistent ASK credentials detected — setup will use existing credentials.</div>'
    except Exception:
        creds_html = ''

    # Compute initial created flag for first render (Done. Skill ID)
    try:
        initial_created = False
        for ln in initial_logs:
            try:
                if re.search(r'Done\.\s*Skill ID', str(ln), re.IGNORECASE):
                    initial_created = True
                    break
            except Exception:
                continue
    except Exception:
        initial_created = False

    if page:
        page = page.replace('__INITIAL_LOGS__', json.dumps(initial_logs))
        page = page.replace('__INITIAL_AUTH__', json.dumps(auth_url))
        page = page.replace('__INITIAL_CREATED__', json.dumps(bool(initial_created)))
        page = page.replace('__CREDENTIALS_HTML__', creds_html)
        return Response(page, mimetype='text/html')

    # Fallback: simple inline page if template is missing
    page = """<!doctype html><html><head><meta charset='utf-8'><title>Skill Setup</title></head><body><h1>Skill Setup</h1><pre>%s</pre></body></html>""" % json.dumps(initial_logs)
    return Response(page, mimetype='text/html')


@app.route('/setup/logs/download', methods=['GET'])
def setup_logs_download():
    try:
        content = '\n'.join(sanitize_log(line) for line in list(_setup_logs))
    except Exception:
        content = '\n'.join(str(line) for line in list(_setup_logs))
    resp = Response(content, mimetype='text/plain')
    resp.headers['Content-Disposition'] = 'attachment; filename="setup_logs.txt"'
    return resp


@app.route('/setup/start', methods=['POST'])
def setup_start():
    global _setup_proc
    # Endpoint is provided via environment (SKILL_HOSTNAME) in container deployments
    data = request.get_json(silent=True) or {}
    endpoint = os.environ.get('SKILL_HOSTNAME', '').strip()
    # Allow override for local testing if provided in request body (kept for compatibility)
    if not endpoint:
        endpoint = data.get('endpoint')
    # Fixed options (user-not-editable). `LOCALE` may be set in the environment.
    profile = 'default'
    locale = os.environ.get('LOCALE', 'en-US')
    stage = 'development'
    upload_models = True

    # Immediate trace so UI shows activity when button is clicked
    try:
        _enqueue_setup_log(f"Received /setup/start request; resolved endpoint={endpoint!r}")
    except Exception:
        _setup_logs.append('Received /setup/start request')

    app.logger.info('setup_start called; resolved endpoint=%s', endpoint)

    if not endpoint:
        _setup_logs.append('Error: SKILL_HOSTNAME environment variable is not set and no endpoint provided')
        return jsonify({'error':'SKILL_HOSTNAME not set; set SKILL_HOSTNAME in container environment'}), 400

    # Normalize endpoint: allow ARN, full URLs, or hostnames (prefix https://)
    def _normalize(ep: str):
        ep = ep.strip()
        if ep.startswith('arn:'):
            return ep
        if ep.startswith('http://') or ep.startswith('https://'):
            return ep
        return 'https://' + ep

    endpoint = _normalize(endpoint)

    # helper: is ASK CLI already configured (simple check)
    def ask_configured():
        cfg = Path.home() / '.ask' / 'cli_config'
        return cfg.exists()

    with _setup_lock:
        # If a setup script is already running, report it
        if _setup_proc and _setup_proc.poll() is None:
            return jsonify({'status':'running'})

        # Ensure ask CLI exists
        try:
            which = subprocess.run(['which','ask'], capture_output=True, text=True)
            if which.returncode != 0:
                _setup_logs.append('Error: ask CLI not installed')
                app.logger.error('ask CLI not installed')
                return jsonify({'error':'ask CLI not installed'}), 500
        except Exception as e:
            _setup_logs.append(f'Error checking ask CLI: {e}')
            app.logger.exception('check failed')
            return jsonify({'error':'check failed'}), 500

        # If ASK CLI is not configured, start the no-browser auth flow and return auth_started
        if not ask_configured():
            with _setup_auth_lock:
                global _setup_auth_proc
                if _setup_auth_proc and _setup_auth_proc.poll() is None:
                    return jsonify({'status':'auth_started'})
                try:
                    app.logger.info('Starting ASK CLI no-browser configure')
                    _setup_logs.append('Starting ASK CLI no-browser configure. Follow the auth URL printed in logs.')
                    # Spawn ask configure inside a pseudo-tty so it prints the auth URL.
                    master_fd, slave_fd = pty.openpty()
                    auth_cmd = ['ask','configure','--no-browser']
                    _setup_auth_proc = subprocess.Popen(auth_cmd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, close_fds=True)
                    os.close(slave_fd)
                    # remember the endpoint requested so we can start creation after auth
                    global _pending_endpoint, _setup_auth_master_fd
                    _pending_endpoint = endpoint
                    try:
                        _PENDING_FILE.write_text(endpoint)
                    except Exception:
                        pass
                    _setup_auth_master_fd = master_fd
                    t = threading.Thread(target=_read_master_loop, args=(master_fd,'ASK'), daemon=True)
                    t.start()
                    # Try to capture any immediate output that may have been written
                    try:
                        time.sleep(0.1)
                        try:
                            initial = os.read(master_fd, 4096)
                        except OSError:
                            initial = b''
                        if initial:
                            try:
                                s = initial.decode('utf-8', errors='replace')
                            except Exception:
                                s = str(initial)
                            for ln in s.splitlines():
                                _enqueue_setup_log(f'[ASK] {ln}')
                    except Exception:
                        pass
                    app.logger.info('ask configure started, pid=%s master_fd=%s', getattr(_setup_auth_proc, 'pid', None), master_fd)
                    return jsonify({'status':'auth_started'})
                except Exception as e:
                    _setup_logs.append(f'Failed to start auth: {e}')
                    app.logger.exception('failed starting ask configure')
                    return jsonify({'error':'failed starting auth'}), 500

        # ASK already configured: start the create script directly
        try:
            # script is installed into the container at /app/scripts by the Dockerfile
            script_path = '/app/scripts/ask_create_skill.sh'
            app.logger.info('Launching setup script: %s', script_path)
            _setup_logs.append(f'Starting setup: endpoint={endpoint} profile={profile} locale={locale} stage={stage}')
            # run the top-level shell script via bash so it behaves like the original shell invocation
            cmd = ['/bin/bash', script_path, '--endpoint', endpoint, '--profile', profile, '--locale', locale, '--stage', stage]
            if not upload_models:
                cmd.append('--no-upload-models')
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            _setup_proc = proc
            t = threading.Thread(target=_setup_reader_thread, args=(proc, 'CREATE'), daemon=True)
            t.start()
            app.logger.info('setup script started, pid=%s', getattr(proc, 'pid', None))
            return jsonify({'status': 'started'})
        except Exception as e:
            _setup_logs.append(f'Failed to start setup script: {e}')
            app.logger.exception('failed starting setup script')
            return jsonify({'error': 'failed starting setup script'}), 500





@app.route('/setup/code', methods=['POST'])
def setup_code():
    """Accept the auth code from the user and forward it to the running `ask configure --no-browser` process.
    After auth completes successfully, start the create-skill script.
    """
    global _setup_auth_proc, _setup_proc
    data = request.get_json(silent=True) or {}
    code = data.get('code')
    if not code:
        return jsonify({'error':'missing code'}), 400

    with _setup_auth_lock:
        if not _setup_auth_proc or _setup_auth_proc.poll() is not None:
            return jsonify({'error':'auth not running'}), 400
        try:
            # Write the code into the pty master so the ask process receives it
            global _setup_auth_master_fd
            if _setup_auth_master_fd is None:
                raise RuntimeError('auth master fd not available')
            os.write(_setup_auth_master_fd, (code + '\n').encode('utf-8'))
            # Attempt to auto-respond 'Y' to the AWS linking prompt that follows
            # the authorization code exchange. Send a short delay then write 'Y\n'
            # if the auth process is still running and the master fd is available.
            try:
                time.sleep(0.2)
                if _setup_auth_master_fd is not None and _setup_auth_proc and _setup_auth_proc.poll() is None:
                    try:
                        os.write(_setup_auth_master_fd, b'n\n')
                        _enqueue_setup_log('[ASK] Auto-responded N to AWS linking prompt')
                    except Exception as _e:
                        _enqueue_setup_log(f'[ASK] Auto-respond N failed: {_e}')
            except Exception:
                pass
        except Exception as e:
            _setup_logs.append(f'Failed to submit code: {e}')
            return jsonify({'error': str(e)}), 500

    # Wait for auth process to exit (short timeout)
    timeout = 120
    waited = 0
    while waited < timeout:
        if _setup_auth_proc.poll() is not None:
            break
        time.sleep(1)
        waited += 1

    rc = _setup_auth_proc.poll()
    if rc is None:
        _setup_logs.append('Auth process did not complete within timeout')
        return jsonify({'error':'auth timeout'}), 500
    if rc != 0:
        _setup_logs.append(f'Auth process exited with code {rc}')
        return jsonify({'error':f'auth failed (rc {rc})'}), 500

    _setup_logs.append('Auth completed successfully; starting skill creation')

    # Now start the create-skill script (use fixed options)
    # Use the pending endpoint saved when auth was started
    global _pending_endpoint
    endpoint_val = _pending_endpoint
    if not endpoint_val:
        # try to recover from tmp file in case the app restarted or state was lost
        try:
            if _PENDING_FILE.exists():
                endpoint_val = _PENDING_FILE.read_text().strip()
                if endpoint_val:
                    _enqueue_setup_log(f'Recovered endpoint from {_PENDING_FILE}')
        except Exception:
            pass
    if not endpoint_val:
        _setup_logs.append('Error: missing endpoint context; call /setup/start first')
        return jsonify({'error':'missing endpoint context; call /setup/start first'}), 400

    # Start the create script now
    try:
        profile = 'default'
        locale = os.environ.get('LOCALE', 'en-US')
        stage = 'development'
        # script is installed into the container at /app/scripts by the Dockerfile
        script_path = '/app/scripts/ask_create_skill.sh'
        # run the shell script via bash (matching the shell behaviour)
        cmd = ['/bin/bash', script_path, '--endpoint', endpoint_val, '--profile', profile, '--locale', locale, '--stage', stage]
        _enqueue_setup_log(f'Starting create script: {cmd}')
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        except Exception as e:
            _enqueue_setup_log(f'Failed to spawn create script: {e}')
            raise
        _setup_proc = proc
        _enqueue_setup_log(f'Create script pid={getattr(proc, "pid", None)}')
        t = threading.Thread(target=_setup_reader_thread, args=(proc,'CREATE'), daemon=True)
        t.start()
        # Quick check: if the process exits immediately, capture and log its output and rc
        time.sleep(0.25)
        try:
            rc = proc.poll()
            if rc is not None:
                _enqueue_setup_log(f'Create script exited immediately with rc={rc}')
                try:
                    out = proc.stdout.read()
                    if out:
                        for ln in out.splitlines():
                            _enqueue_setup_log(f'[CREATE-OUT] {ln}')
                except Exception:
                    pass
        except Exception as e:
            _enqueue_setup_log(f'Error while checking create script immediate status: {e}')
        # clear pending endpoint after starting
        _pending_endpoint = None
        try:
            if _PENDING_FILE.exists():
                _PENDING_FILE.unlink()
        except Exception:
            pass
        return jsonify({'status':'started'})
    except Exception as e:
        _setup_logs.append(f'Failed to start setup script after auth: {e}')
        return jsonify({'error':'failed to start setup script after auth'}), 500


@app.route('/setup/stop', methods=['POST'])
def setup_stop():
    global _setup_proc
    with _setup_lock:
        if not _setup_proc:
            return jsonify({'status':'no-process'})
        try:
            _setup_proc.terminate()
        except Exception:
            pass
        _setup_proc = None
    return jsonify({'status':'stopped'})


if __name__ == "__main__":
    port = int(os.environ.get('PORT', '5000'))
    # Respect FLASK_DEBUG (1 enables debug mode) and FLASK_RELOADER (1 enables reloader)
    flask_debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    if flask_debug:
        use_reloader = os.environ.get('FLASK_RELOADER', '0') == '1'
        app.run(debug=True, use_reloader=use_reloader, host="0.0.0.0", port=port)
    else:
        # Production/dev host mode: don't use the reloader to avoid transient restarts
        app.run(debug=False, host="0.0.0.0", port=port)
