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

| Variable             | Required | Default           | Description                                                                                             |
| -------------------- | :------: | ----------------- | ------------------------------------------------------------------------------------------------------- |
| `SKILL_HOSTNAME`     |   Yes    | —                 | Public HTTPS hostname used in the Alexa skill manifest and endpoint validation.                         |
| `MA_HOSTNAME`        |    No    | —                 | Music Assistant server hostname. Required if your device does not support APL or if you want album art. |
| `APP_USERNAME`       |    No    | —                 | Username for the Music Assistant web UI and API basic authentication.                                   |
| `APP_PASSWORD`       |    No    | —                 | Password for the Music Assistant web UI and API basic authentication.                                   |
| `PORT`               |    No    | `5000`            | Port the service listens on inside the container.                                                       |
| `DEBUG_PORT`         |    No    | `5678`            | Remote debug port for `debugpy`.                                                                        |
| `LOCALE`             |    No    | `en-US`           | Skill locale used by setup and interaction model operations.                                            |
| `AWS_DEFAULT_REGION` |    No    | `us-east-1`       | AWS region used by ASK CLI operations when needed.                                                      |
| `TZ`                 |    No    | `America/Chicago` | Container timezone used for logs and timestamps.                                                        |

### Notes

- The add-on Dockerfile copies the repository into the image and runs the Flask-based service at `app/app.py`.
- The image includes the packages needed to build Python dependencies from `requirements.txt`.
- If `DEBUG_PORT` is enabled, the container starts the app under `debugpy` so VS Code can attach to it.
- This add-on is provided as a development convenience. For production or publication to the official add-on store, additional hardening and configuration is recommended.
