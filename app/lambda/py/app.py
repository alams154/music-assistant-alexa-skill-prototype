import os
from flask import Flask, request, jsonify, Response, redirect
from flask_ask_sdk.skill_adapter import SkillAdapter
from lambda_function import sb  # sb is the SkillBuilder from lambda_function.py
import requests
from requests.exceptions import RequestException
import music_assistant_alexa_api as maa_api
from werkzeug.middleware.dispatcher import DispatcherMiddleware

app = Flask(__name__)
skill_id_env = os.environ.get('SKILL_ID') or ""
skill_adapter = SkillAdapter(
    skill=sb.create(),
    skill_id=skill_id_env,
    app=app)

# Mount the Music Assistant Alexa API
ma_app = maa_api.create_app()
app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {'/ma': ma_app.wsgi_app})
app.logger.info('Mounted music-assistant-alexa-api app at /ma')

@app.route("/", methods=["POST"])
def invoke_skill():
    return skill_adapter.dispatch_request()


@app.route("/status", methods=["GET"])
def status():
    """Simple GET status page for health checks and browsing."""
    api_user = os.environ.get('API_USERNAME')
    api_pass = os.environ.get('API_PASSWORD')

    # Skill adapter status (we're running if this handler is invoked)
    skill_html = '<span class="led green"></span> Skill adapter running'
    # API status: call the locally mounted /ma/latest-url endpoint on this service.
    # Use the current request host (including port) so this works in container
    # and local runs without requiring an external API_HOSTNAME env var.
    endpoint = request.host_url.rstrip('/') + '/ma/latest-url'

    try:
        auth = (api_user, api_pass) if api_user and api_pass else None
        resp = requests.get(endpoint, timeout=2, auth=auth)
        if resp.ok:
            api_html = f'<span class="led green"></span> API reachable ({resp.status_code}) — /ma/latest-url'
        else:
            api_html = f'<span class="led red"></span> API responded {resp.status_code} for /ma/latest-url'
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
                <hr>
                <div class="muted">API host: local (mounted /ma)</div>
                <div class="muted">Checked endpoint: {endpoint}</div>
            </body>
            </html>"""

    return Response(html, status=200, mimetype="text/html")

if __name__ == "__main__":
    port = int(os.environ.get('PORT', '5000'))
    app.run(debug=True, host="0.0.0.0", port=port)
