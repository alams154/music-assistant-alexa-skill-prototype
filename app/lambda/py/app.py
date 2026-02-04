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
import sys
from pathlib import Path
import time
import pty
import re


def sanitize_log(s: str) -> str:
    """Sanitize a log line for UI display: strip carriage returns, remove ANSI/escape
    sequences and redact authorization codes so they do not appear in the status UI.
    """
    try:
        if not isinstance(s, str):
            s = str(s)
    except Exception:
        s = ''
    # Remove literal JSON-escaped ESC sequences that may appear (e.g. "\\u001b")
    s = s.replace('\\u001b', '')
    # Remove carriage returns introduced by some CLI outputs
    s = s.replace('\r', '')
    # Strip ANSI escape sequences (CSI and common ESC patterns)
    try:
        s = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', s)
    except Exception:
        pass
    # If the line references the authorization code prompt, redact any following text
    if 'authorization code' in s.lower():
        s = re.sub(r'(?i)(authorization code[:]?\s*).*', r"\1<REDACTED-AUTH-CODE>", s)
    return s

app = Flask(__name__)
skill_adapter = SkillAdapter(
    skill=sb.create(),
    skill_id="",
    app=app)

# Mount the Music Assistant Alexa API (only ma routes will be mounted at /ma)
ma_app = maa_api.create_ma_app()

# Respect X-Forwarded-* headers when running behind a reverse proxy so
# `request.host_url` and `request.scheme` reflect the external client URL.
# Apply ProxyFix to both apps before wiring the dispatcher.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
ma_app.wsgi_app = ProxyFix(ma_app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {'/ma': ma_app.wsgi_app})
app.logger.info('Mounted music-assistant-alexa-api app at /ma')

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
    try:
        _setup_logs.append(sanitize_log(line))
    except Exception:
        try:
            _setup_logs.append(str(line))
        except Exception:
            pass


def _setup_reader_thread(proc, prefix=None):
    try:
        for line in proc.stdout:
            if not line:
                continue
            text = line.rstrip('\n')
            if prefix:
                text = f'[{prefix}] {text}'
            _enqueue_setup_log(text)
    except Exception as e:
        _enqueue_setup_log(f"[reader error] {e}")


def _read_master_loop(master_fd, prefix=None):
    try:
        buf = b''
        while True:
            try:
                chunk = os.read(master_fd, 1024)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            # Emit full lines when present
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                text = line.decode('utf-8', errors='replace')
                if prefix:
                    text = f'[{prefix}] {text}'
                _enqueue_setup_log(text)
            # Also search for URLs in the received chunk and emit them immediately
            try:
                s = chunk.decode('utf-8', errors='replace')
                for m in re.findall(r"https?://[^\s'\"]+", s):
                    txt = m
                    if prefix:
                        txt = f'[{prefix}] {txt}'
                    _enqueue_setup_log(txt)
            except Exception:
                pass
        if buf:
            # Emit any remaining buffered text (partial line)
            text = buf.decode('utf-8', errors='replace')
            if text.strip():
                if prefix:
                    text = f'[{prefix}] {text}'
                _enqueue_setup_log(text)
    except Exception as e:
        _enqueue_setup_log(f"[pty reader error] {e}")


@app.route("/", methods=["POST"])
def invoke_skill():
    return skill_adapter.dispatch_request()


@app.route("/status", methods=["GET"])
def status():
    """Simple GET status page for health checks and browsing."""
    api_user = get_env_secret('API_USERNAME')
    api_pass = get_env_secret('API_PASSWORD')

    # Skill adapter status (we're running if this handler is invoked)
    skill_html = '<span class="led green"></span> Skill running'
    # API status: call the locally mounted /ma/latest-url endpoint on this service.
    # Use the current request host (including port) so this works in container
    # and local runs without requiring an external API_HOSTNAME env var.
    endpoint = request.host_url.rstrip('/') + '/ma/latest-url'

    try:
        auth = (api_user, api_pass) if api_user and api_pass else None
        resp = requests.get(endpoint, timeout=2, auth=auth)
        # Include a short, escaped preview of the response content when the API responded
        try:
            content_text = resp.content.decode('utf-8', errors='replace')
        except Exception:
            content_text = str(resp.content)

        # If the response is JSON, pretty-print it for readability; otherwise escape raw text.
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

    html = f"""<!doctype html>
            <html>
            <head>
                <meta charset="utf-8">
                <link rel="icon" type="image/svg+xml" href="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0%200%20100%20100'><circle cx='50' cy='50' r='50' fill='%2300A4E3'/><circle cx='50' cy='50' r='34' fill='none' stroke='%23FFFFFF' stroke-width='8' opacity='0.8'/></svg>">
                <title>Service Status</title>
                <style>
                body {{ font-family: Arial, Helvetica, sans-serif; padding: 20px; }}
                .led {{ display:inline-block; width:14px; height:14px; border-radius:50%; margin-right:8px; }}
                .green {{ background:#2ecc71; }}
                .red {{ background:#e74c3c; }}
                .row {{ margin: 8px 0; }}
                .muted {{ color:#666; font-size:0.9em }}
                </style>
            </head>
            <body>
                <h1>Service Status</h1>
                <div class="row">{skill_html}</div>
                <div class="row">{api_html}</div>
                <div class="row"><a href="/setup">Skill Setup</a></div>
            </body>
            </html>"""

    return Response(html, status=200, mimetype="text/html")


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
            safe_logs = [sanitize_log(l) for l in list(_setup_logs)]
        except Exception:
            safe_logs = list(_setup_logs)
        return jsonify({'logs': safe_logs, 'auth_url': auth_url, 'active': bool(active)})

    page = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Skill Setup</title></head>
<body>
    <h1>Skill Setup</h1>
    <div>
        <div style="margin-bottom:8px;">Endpoint is read from container configuration (SKILL_HOSTNAME)</div>
        <div><button id="setup-start">Start Setup</button></div>
        <div id="auth-area" style="display:none;margin-top:8px">
            <div><a id="auth-link" href="#" target="_blank">Open authorization page</a></div>
            <div id="code-entry" style="display:none">
                <form id="code-form"><input id="auth-code" name="code" type="password" autocomplete="one-time-code"/><button>Submit Code</button></form>
                <div id="code-result"></div>
            </div>
        </div>
        <div style="margin-top:8px;font-weight:600">Setup Logs</div>
        <pre id="setup-logs" tabindex="0" style="max-height:300px;overflow:auto;background:#f6f6f6;padding:8px"></pre>
        <div style="margin-top:8px"><button id="download-logs">Download logs</button></div>
    </div>
    <script>
    const initialLogs = __INITIAL_LOGS__;
    const initialAuth = __INITIAL_AUTH__;
    (function(){
        const startBtn = document.getElementById('setup-start');
        const logsEl = document.getElementById('setup-logs');
        const authArea = document.getElementById('auth-area');
        const authLink = document.getElementById('auth-link');
        const codeEntry = document.getElementById('code-entry');
        const codeForm = document.getElementById('code-form');
        // Track whether we've already opened the auth URL in a tab/window
        let authOpened = false;
        const downloadBtn = document.getElementById('download-logs');

        function renderInitial(){
            // Render any initial logs/auth embedded in the page
            try{ logsEl.textContent = JSON.stringify(initialLogs || [], null, 2); logsEl.scrollTop = logsEl.scrollHeight; }catch(e){ logsEl.textContent = ''; }
            if(initialAuth){
                authArea.style.display='block';
                authLink.href = initialAuth;
                authLink.textContent = 'Open authorization page';
                codeEntry.style.display='block';
                if(!authOpened){ try{ window.open(initialAuth, '_blank'); authOpened = true; }catch(e){} }
            }
            // Start adaptive polling loop
            pollLogs();
        }

        // Make the logs box focusable and intercept Cmd/Ctrl+A to select only the logs
        logsEl.addEventListener('click', function(){ logsEl.focus(); });
        logsEl.addEventListener('keydown', function(e){
            const key = (e.key || '').toLowerCase();
            if ((e.ctrlKey || e.metaKey) && key === 'a'){
                e.preventDefault();
                try{
                    const range = document.createRange();
                    range.selectNodeContents(logsEl);
                    const sel = window.getSelection();
                    sel.removeAllRanges();
                    sel.addRange(range);
                }catch(err){ /* ignore */ }
            }
        });

        function pollLogs(){
            fetch('/setup?format=json').then(r=>r.json()).then(j=>{
                try{ logsEl.textContent = JSON.stringify(j.logs || [], null, 2); logsEl.scrollTop = logsEl.scrollHeight; }catch(e){ logsEl.textContent = ''; }
                if(j.auth_url){
                    authArea.style.display='block';
                    authLink.href = j.auth_url;
                    authLink.textContent = 'Open authorization page';
                    codeEntry.style.display='block';
                    if(!authOpened){ try{ window.open(j.auth_url, '_blank'); authOpened = true; }catch(e){} }
                }
                // Schedule next poll: more frequent when active, otherwise back off
                const next = j.active ? 3000 : 15000;
                setTimeout(pollLogs, next);
            }).catch(()=>{ setTimeout(pollLogs, 15000); });
        }

        startBtn.addEventListener('click', function(){
            fetch('/setup/start', {method:'POST'}).then(async (r)=>{
                let j = {};
                try{ j = await r.json(); }catch(e){}
                if(!r.ok){ logsEl.textContent = (j.error || JSON.stringify(j) || 'Error starting setup'); }
                else { if(j.status === 'auth_started'){ authArea.style.display='block'; pollLogs(); } else { pollLogs(); } }
            }).catch(()=>{ logsEl.textContent = 'Start request failed'; });
        });

        downloadBtn.addEventListener('click', function(){
            // Navigate to download endpoint to trigger browser download
            window.location = '/setup/logs/download';
        });
        codeForm.addEventListener('submit', function(ev){
            ev.preventDefault();
            const codeInput = document.getElementById('auth-code');
            const code = codeInput.value.trim();
            if(!code) return;
            // Clear the input after submission so the code isn't left visible
            try{ codeInput.value = ''; }catch(e){}
            // Remove the code result div from the DOM (it's no longer needed)
            try{
                const resultEl = document.getElementById('code-result');
                if(resultEl && resultEl.parentNode){ resultEl.parentNode.removeChild(resultEl); }
            }catch(e){}
            fetch('/setup/code', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({code})}).then(r=>r.json()).then(j=>{
                // Do not persist the server response in the UI; hide inputs if creation started
                if(j.status === 'started'){ codeEntry.style.display='none'; }
                // kick the poll loop once immediately to refresh logs
                pollLogs();
            }).catch(()=>{
                // On error, recreate a small result element to show failure
                try{
                    let resultEl = document.getElementById('code-result');
                    if(!resultEl){ resultEl = document.createElement('div'); resultEl.id = 'code-result'; codeEntry.appendChild(resultEl); }
                    resultEl.textContent = 'Submit failed';
                }catch(e){}
            });
        });

        renderInitial();
    })();
    </script>
</body>
</html>"""
    page = page.replace('__INITIAL_LOGS__', json.dumps(initial_logs))
    page = page.replace('__INITIAL_AUTH__', json.dumps(auth_url))
    return Response(page, mimetype='text/html')


@app.route('/setup/logs/download', methods=['GET'])
def setup_logs_download():
    try:
        content = '\n'.join(sanitize_log(l) for l in list(_setup_logs))
    except Exception:
        content = '\n'.join(str(l) for l in list(_setup_logs))
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
    # Fixed options (user-not-editable)
    profile = 'default'
    locale = 'en-US'
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
        locale = 'en-US'
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
