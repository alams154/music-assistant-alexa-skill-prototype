# Music Assistant Alexa Skill — Home Assistant Add-on

This folder contains a simple Home Assistant add-on wrapper for the `music-assistant-alexa-skill-prototype` project. It's intended for development and local testing inside Home Assistant Supervisor.

Installation (development):

1. Copy the `addons/music-assistant-skill` folder into a Git repository that you expose to Home Assistant as an add-on store (or add this repository as a custom add-on repository in Supervisor).
2. In the Supervisor > Add-on Store, add the repository URL for the repo containing this `addons` folder.
3. Install the "Music Assistant Alexa Skill" add-on and start it.

Configuration options (in Supervisor add-on configuration):

- `MA_HOSTNAME`: optional hostname for your Music Assistant instance.
- `APP_USERNAME` / `APP_PASSWORD`: credentials to authenticate to the Music Assistant web UI and API (optional).
- `PORT`: port the service listens on inside the container (default 5000).
- `DEBUG_PORT`: optional debug port (default 5678).
- `AWS_DEFAULT_REGION`: AWS region used by the skill when needed (default `us-east-1`).

Notes:

- The add-on Dockerfile copies the whole repository into the image and runs the Flask-based service at `app/app.py`.
- Additional system packages are installed to be able to build Python packages from `requirements.txt`.
- This add-on is provided as a development convenience. For production or publishing to the official add-on store further hardening and configuration is recommended.
