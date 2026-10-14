#!/usr/bin/env python3
"""Resolve Nabu Casa remote UI URLs for the Alexa skill and audio stream.

When USE_NABU_CASA is on, always prints shell exports for SKILL_HOSTNAME and
MA_HOSTNAME from the remote host. User-set values for those options are
ignored. Home Assistant Cloud remote access must be connected.
"""
import json
import shlex
import socket
import sys
import time
import urllib.error
import urllib.request

# /core/api is Supervisor's proxy for Home Assistant's /api.
# /core/api/states is /api/states, so these paths must not repeat /api.
API = "http://supervisor/core/api"
DOMAIN = "music_assistant_alexa_skill"
PORT = 5000
REGISTER_PATH = f"/{DOMAIN}/register"
FLOW_PATH = "/config/config_entries/flow"


def _token():
    import os
    return (os.environ.get("SUPERVISOR_TOKEN") or "").strip()


def _request(method, path, payload=None):
    token = _token()
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8")
        if not raw:
            return resp.status, {}
        return resp.status, json.loads(raw)


def _addon_base_url():
    host = socket.gethostname().strip()
    return f"http://{host}:{PORT}"


def _register():
    status, body = _request(
        "POST",
        REGISTER_PATH,
        {"addon_base_url": _addon_base_url()},
    )
    return status, body


def _ensure_config_entry():
    """Create the integration entry when Home Assistant has loaded it."""
    try:
        status, body = _request(
            "POST",
            FLOW_PATH,
            {"handler": DOMAIN},
        )
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return False
        detail = err.read().decode("utf-8", errors="replace")
        print(f"Config flow failed: {err.code} {detail}", file=sys.stderr)
        return False

    if body.get("type") == "create_entry":
        return True
    if body.get("type") == "abort" and body.get("reason") == "single_instance_allowed":
        return True
    flow_id = body.get("flow_id")
    if body.get("type") == "form" and flow_id:
        try:
            _, stepped = _request(
                "POST",
                f"{FLOW_PATH}/{flow_id}",
                {},
            )
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="replace")
            print(f"Config flow step failed: {err.code} {detail}", file=sys.stderr)
            return False
        if stepped.get("type") in ("create_entry", "abort"):
            return stepped.get("type") == "create_entry" or stepped.get("reason") == "single_instance_allowed"
    print(f"Unexpected config flow result: {body}", file=sys.stderr)
    return status == 200 and body.get("type") == "create_entry"


def exports_for(body):
    """Shell lines to eval, plus warnings that should not abort startup.

    Always overwrites SKILL_HOSTNAME and MA_HOSTNAME from the remote URLs.
    """
    lines = []
    warnings = []
    skill = (body.get("skill_url") or "").strip()
    stream = (body.get("remote_stream_url") or "").strip()
    if skill.startswith("https://"):
        lines.append(f"export SKILL_HOSTNAME={shlex.quote(skill)}")
    if stream.startswith("https://"):
        lines.append(f"export MA_HOSTNAME={shlex.quote(stream)}")

    if not skill.startswith("https://") or not stream.startswith("https://"):
        if body.get("remote_enabled") and not body.get("remote_connected"):
            warnings.append(
                "Home Assistant Cloud remote access is enabled but not connected yet."
            )
        elif not body.get("remote_enabled"):
            warnings.append(
                "Turn on Home Assistant Cloud remote access so Alexa and Echo "
                "can reach this skill through your *.ui.nabu.casa address."
            )

    if stream.startswith("https://") and not (body.get("ma_stream_base") or "").strip():
        warnings.append(
            "Music Assistant add-on was not found or is not started. "
            "Audio forwarding starts once that add-on is running."
        )
    return lines, warnings


def main():
    if not _token():
        print(
            "SUPERVISOR_TOKEN is missing, so this add-on cannot ask Home Assistant for a Nabu Casa URL.",
            file=sys.stderr,
        )
        return 1

    last_error = "Home Assistant API did not respond"
    for attempt in range(1, 6):
        try:
            _, body = _register()
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="replace")
            if err.code == 404:
                if _ensure_config_entry():
                    continue
                last_error = (
                    "The Music Assistant Alexa Skill integration is not loaded yet. "
                    "Start this add-on once, restart Home Assistant, add the "
                    "Music Assistant Alexa Skill integration under Devices & services, "
                    "turn on Cloud remote access, then start this add-on again."
                )
            else:
                last_error = f"HTTP {err.code}: {detail}"
                if err.code in (401, 403):
                    print(last_error, file=sys.stderr)
                    return 1
                if err.code == 503:
                    try:
                        body = json.loads(detail) if detail else {}
                    except Exception:
                        body = {}
                    if isinstance(body, dict) and (
                        body.get("remote_enabled") is not None
                        or "remote" in (body.get("error") or "").lower()
                    ):
                        last_error = body.get("error") or last_error
                        if attempt < 5:
                            time.sleep(3)
                            continue
                    print(last_error, file=sys.stderr)
                    return 1
        except urllib.error.URLError as err:
            last_error = str(err.reason)
        except Exception as err:
            last_error = str(err)
        else:
            lines, warnings = exports_for(body)
            waiting_for_remote = (
                body.get("remote_enabled")
                and not body.get("remote_connected")
                and attempt < 5
            )
            if waiting_for_remote:
                time.sleep(3)
                continue
            skill = (body.get("skill_url") or "").strip()
            stream = (body.get("remote_stream_url") or "").strip()
            if skill.startswith("https://") and stream.startswith("https://"):
                print("\n".join(lines))
                print(f"Nabu Casa skill URL: {skill}", file=sys.stderr)
                print(f"Nabu Casa stream URL: {stream}", file=sys.stderr)
                for warning in warnings:
                    print(warning, file=sys.stderr)
                return 0
            last_error = body.get("error") or "remote skill or stream URL missing"
            if "not connected" in last_error.lower() or "remote access" in last_error.lower():
                print(last_error, file=sys.stderr)
                return 1
        if attempt < 5:
            time.sleep(3)

    print(f"Could not get Nabu Casa remote URLs: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
