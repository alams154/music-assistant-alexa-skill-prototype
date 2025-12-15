import os
from flask import Flask, request, jsonify, Response
from flask_ask_sdk.skill_adapter import SkillAdapter
from lambda_function import sb  # sb is the SkillBuilder from lambda_function.py
import requests
from requests.exceptions import RequestException

app = Flask(__name__)
skill_adapter = SkillAdapter(
    skill=sb.create(), 
    skill_id="<>",  # Replace with your actual skill ID
    app=app)

@app.route("/", methods=["POST"])
def invoke_skill():
    return skill_adapter.dispatch_request()


@app.route("/status", methods=["GET"])
def status():
    """Simple GET status page for health checks and browsing."""
    api_host = os.environ.get("API_HOSTNAME")
    api_user = os.environ.get("API_USERNAME")
    api_pass = os.environ.get("API_PASSWORD")

    # Skill adapter status (we're running if this handler is invoked)
    skill_html = '<span class="led green"></span> Skill adapter running'

    # API status
    if not api_host:
        api_html = '<span class="led red"></span> API_HOSTNAME not set'
    else:
        # Ensure scheme and target the /ma/latest-url endpoint
        if api_host.startswith("http://") or api_host.startswith("https://"):
            base = api_host
        else:
            base = f"http://{api_host}"

        endpoint = base.rstrip('/') + '/ma/latest-url'

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
                <div class="muted">API host: {api_host or 'not set'}</div>
                <div class="muted">Checked endpoint: {endpoint if api_host else 'n/a'}</div>
            </body>
            </html>"""

    return Response(html, status=200, mimetype="text/html")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
