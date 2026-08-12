# -*- coding: utf-8 -*-
"""Persistent mapping of Alexa device_id -> Music Assistant player_id.

Alexa's Custom Skill API only exposes an opaque, per-skill device_id in
the request context - there is no way to resolve it to a friendly device
name or to the corresponding MA player. The id is stable per device
though, so a one-time manual mapping (configured via the /devices page)
is a durable workaround.
"""

import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

_DEFAULT_PATH = "/app/instance_data/device_players.json"
_lock = threading.Lock()


def _path():
    return os.environ.get("DEVICE_MAPPING_PATH", _DEFAULT_PATH)


def load_mapping():
    """Return the device_id -> player_id mapping dict (empty if none saved yet)."""
    path = _path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except FileNotFoundError:
        return {}
    except Exception:
        logger.exception("Failed to read device mapping from %s", path)
    return {}


def save_mapping(mapping):
    path = _path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with _lock:
            tmp_path = path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(mapping, f, indent=2, sort_keys=True)
            os.replace(tmp_path, path)
        return True
    except Exception:
        logger.exception("Failed to write device mapping to %s", path)
        return False


def get_player_for_device(device_id):
    if not device_id:
        return None
    return load_mapping().get(device_id)


def set_player_for_device(device_id, player_id):
    mapping = load_mapping()
    if player_id:
        mapping[device_id] = player_id
    else:
        mapping.pop(device_id, None)
    return save_mapping(mapping)
