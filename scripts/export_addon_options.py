#!/usr/bin/env python3
"""Print shell export lines for Home Assistant add-on options.

Supervisor writes the add-on configuration to /data/options.json. The
container entrypoint evaluates this script's stdout before starting the
app so values such as TZ and AWS_DEFAULT_REGION exist in the environment
before Python imports.
"""
import json
import shlex
import sys
from pathlib import Path

OPTIONS_PATH = Path("/data/options.json")


def _valid_key(key):
    return (
        isinstance(key, str)
        and key.isidentifier()
        and key.upper() == key
        and not key[0].isdigit()
    )


def main():
    if not OPTIONS_PATH.is_file():
        return 0
    try:
        options = json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Failed to read {OPTIONS_PATH}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(options, dict):
        print(f"{OPTIONS_PATH} is not an object", file=sys.stderr)
        return 1

    for key, value in options.items():
        if not _valid_key(key) or value is None or value == "":
            continue
        if isinstance(value, bool):
            text = "true" if value else "false"
        else:
            text = str(value)
        print(f"export {key}={shlex.quote(text)}")

    if not options.get("ASK_CREDENTIALS_DIR"):
        print("export ASK_CREDENTIALS_DIR=/data/.ask")
    if not options.get("DEVICE_MAPPING_PATH"):
        print("export DEVICE_MAPPING_PATH=/data/device_players.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
