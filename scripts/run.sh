#!/bin/sh
# Container entrypoint for Docker Compose and the Home Assistant add-on.
# When Supervisor has written /data/options.json, export those values first.
set -eu
cd /app

if [ -f /data/options.json ]; then
  eval "$(/app/venv/bin/python /app/scripts/export_addon_options.py)"
  ask_dir="${ASK_CREDENTIALS_DIR:-/data/.ask}"
  export ASK_CREDENTIALS_DIR="$ask_dir"
  export HOME="$(dirname "$ask_dir")"
  mkdir -p "$ask_dir"
  map_path="${DEVICE_MAPPING_PATH:-/data/device_players.json}"
  export DEVICE_MAPPING_PATH="$map_path"
  mkdir -p "$(dirname "$map_path")"
fi

if [ "${USE_NABU_CASA:-false}" = "true" ]; then
  if [ -d /homeassistant ]; then
    mkdir -p /homeassistant/custom_components/music_assistant_alexa_skill
    cp -a /app/custom_components/music_assistant_alexa_skill/. /homeassistant/custom_components/music_assistant_alexa_skill/
  else
    echo "Home Assistant config is not mounted, so the Nabu Casa integration could not be installed." >&2
  fi
  if nabu_exports="$(/app/venv/bin/python /app/scripts/resolve_nabu_casa.py)"; then
    eval "$nabu_exports"
  else
    echo "Continuing without a Nabu Casa skill URL." >&2
  fi
fi

if [ -n "${DEBUG_PORT:-}" ] && [ "${DEBUG_PORT}" != "0" ]; then
  exec /app/venv/bin/python -m debugpy --listen "0.0.0.0:${DEBUG_PORT}" /app/src/app.py
fi
exec /app/venv/bin/python /app/src/app.py
