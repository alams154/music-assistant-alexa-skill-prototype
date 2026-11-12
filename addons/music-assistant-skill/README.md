# Music Assistant Alexa Skill - Home Assistant Add-on

This folder contains the Home Assistant add-on wrapper for the `music-assistant-alexa-skill-prototype` project. It is intended for development and local testing inside Home Assistant Supervisor.

## How to Run

### Prerequisites

- Home Assistant Supervisor running with add-on support
- A repository containing this `addons/music-assistant-skill` folder added to the Supervisor add-on store
- A public HTTPS endpoint for the skill, if you plan to test the full Alexa flow

### 1. Install the add-on

1. Add this repository as a custom add-on repository in Home Assistant Supervisor.
2. Open Supervisor > Add-on Store and install the "Music Assistant Alexa Skill" add-on.
3. Open the add-on configuration and set the options below as needed.
4. Start the add-on and check the logs for startup and configuration issues.

### 2. Access the service

- The web UI is available on the configured `PORT` (default `5000`).
- The `/setup` page guides you through ASK CLI setup and skill provisioning.
- The `/status` page shows a quick health check for the local service and skill configuration.

### Configuration Options

Set these in the Supervisor add-on configuration:

| Variable | Required | Default | Description |
| --- | :---: | --- | --- |
| `SKILL_HOSTNAME` | Yes | — | Public HTTPS hostname used in the Alexa skill manifest and endpoint validation. |
| `SKILL_ID` | No | — | Optional Alexa skill ID (`amzn1.ask.skill.…`) to restrict request verification to your skill. |
| `MA_HOSTNAME` | No | — | Music Assistant stream hostname. Required for non-APL Echo devices, or for album art if `IMAGE_PROXY_VIA_SKILL` is false. |
| `IMAGE_PROXY_VIA_SKILL` | No | `false` | Proxy Music Assistant `/imageproxy/<id>` artwork through `https://<SKILL_HOSTNAME>/imageproxy/<id>` for Echo Show APL devices without exposing Music Assistant publicly. |
| `MA_IMAGE_BASE_URL` | No | `http://127.0.0.1:8095` | Internal Music Assistant web base URL used when `IMAGE_PROXY_VIA_SKILL=true`. |
| `ENABLE_APL` | No | `false` | Enable rich APL rendering (cover art, track text, controls) on screen Echos. |
| `APP_USERNAME` | No | — | Username or path to secret file under `/share/...` for web UI and API basic auth. |
| `APP_PASSWORD` | No | — | Password or path to secret file under `/share/...` for web UI and API basic auth. |
| `ASK_CREDENTIALS_DIR` | No | `/data/.ask` | Persistent directory for ASK CLI credentials across add-on rebuilds. |
| `SKIP_URL_VALIDATION` | No | `false` | Skip server-side HEAD/GET validation of rewritten stream URLs before returning `AudioPlayer.Play`. |
| `QUIET_HTTP` | No | `"1"` | Set `"1"` to suppress noisy library HTTP logs. |
| `MA_API_URL` | No | — | Music Assistant WebSocket/API URL for Next/Previous voice control. |
| `MA_API_TOKEN` | No | — | Long-lived Music Assistant token (or `/share/...` file path). |
| `PORT` | No | `5000` | Port the service listens on inside the container. |
| `WAITRESS_THREADS` | No | `8` | Worker thread count for Waitress WSGI server. |
| `DEBUG_PORT` | No | `0` | Optional remote debug port for `debugpy` (`0` disables debugpy). |
| `LOCALE` | No | `en-US` | Skill locale used by setup and interaction model operations. |
| `AWS_DEFAULT_REGION` | No | `us-east-1` | AWS region used by ASK CLI operations when needed. |
| `TZ` | No | `UTC` | Container timezone used for logs and timestamps. |

### Notes

- The add-on is configured to pull the prebuilt container image from GHCR (`ghcr.io/alams154/music-assistant-skill:<version>`).
- The image includes the packages needed to build Python dependencies from `requirements.txt`.
- If `DEBUG_PORT` is enabled, the container starts the app under `debugpy` so VS Code can attach to it.
- This add-on is provided as a development convenience. For production or publication to the official add-on store, additional hardening and configuration is recommended.
