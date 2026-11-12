# -*- coding: utf-8 -*-
import gettext
_ = gettext.gettext

import json
import os
import sys
import logging
import threading
from typing import Optional
from env_secrets import get_env_secret
import urllib.request
import urllib.error
from urllib.parse import quote
import base64
import re

# Fuege /app/src/ zum Python-Pfad hinzu
_app_src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _app_src not in sys.path:
    sys.path.insert(0, _app_src)

WELCOME_MSG = _("")
HELP_MSG = _("Welcome to {}. You can play, stop, resume listening.  How can I help you ?")
UNHANDLED_MSG = _("Sorry, I could not understand what you've just said.")
CANNOT_SKIP_MSG = _("This is radio, you have to wait for previous or next track to play.")
RESUME_MSG = _("Resuming {}")
NOT_POSSIBLE_MSG = _("This is radio, you can not do that.  You can ask me to stop or pause to stop listening.")
STOP_MSG = _("")
DEVICE_NOT_SUPPORTED = _("Sorry, this skill is not supported on this device")
DEVICE_NOT_MAPPED_MSG = _("This device is not paired with a Music Assistant player yet. Please configure it on the status page.")
MA_COMMAND_FAILED_MSG = _("Sorry, I could not reach Music Assistant to skip the track.")

info = {
    "audioSources": "",
    "backgroundImageSource": "",
    "coverImageSource": "",
    "headerAttributionImage": "",
    "headerTitle": "",
    "headerSubtitle": "",
    "primaryText": "",
    "secondaryText": ""
}

def _build_info_dict(payload):
    """Normalize stream/artwork URLs and format APL metadata from a store payload."""
    stream_url = payload.get('streamUrl') or ''
    title = payload.get('title', '') or ''
    artist = payload.get('artist', '') or ''
    album = payload.get('album', '') or ''
    image = payload.get('imageUrl') or ''

    secondary = ''
    if artist and album:
        secondary = f"{artist} - {album}"
    elif artist:
        secondary = artist
    elif album:
        secondary = album

    if stream_url and isinstance(stream_url, str):
        try:
            stream_url = re.sub(r'(?i)\.flac(?=$|\?)', '.mp3', stream_url)
            stream_url = quote(stream_url, safe=':/%?=&')
        except Exception:
            logging.exception('Failed rewriting stream URL extension for %s', stream_url)
    if image and isinstance(image, str):
        image = quote(image, safe=':/%?=&')

    return {
        'audioSources': stream_url,
        'backgroundImageSource': image,
        'coverImageSource': image,
        'headerAttributionImage': '',
        'headerTitle': '',
        'headerSubtitle': '',
        'primaryText': title,
        'secondaryText': secondary,
    }


_meta_lock = threading.Lock()
_device_meta_sig = {}


def get_latest(
    api_hostname=None,
    path='/ma/latest-url',
    scheme='http',
    timeout=5,
    username=None,
    password=None,
    device_id=None,
    prefer_latest=False,
    track_changes=False,
):
    global info

    try:
        import shared_store
        from . import device_mapping
        mapped_player = device_mapping.get_player_for_device(device_id) if device_id else None
        payload = shared_store.get_ma_stream(
            device_id=device_id,
            mapped_player=mapped_player,
            prefer_latest=prefer_latest,
        )
        if payload and payload.get('streamUrl'):
            entry = _build_info_dict(payload)
            sig = (
                payload.get('version'),
                payload.get('playerKey'),
                entry['audioSources'],
                entry['primaryText'],
                entry['secondaryText'],
                entry['coverImageSource'],
            )
            sig_key = device_id or '_default'
            with _meta_lock:
                prev_sig = _device_meta_sig.get(sig_key)
                changed = (prev_sig != sig) if track_changes else True
                _device_meta_sig[sig_key] = sig
                if not device_id or payload == shared_store._store or changed:
                    info.update(entry)

            if not track_changes or changed:
                logging.info('Loaded from shared_store: %s - %s', entry['primaryText'], entry['audioSources'][:80])
            return {'changed': changed, 'info': entry, 'playerKey': payload.get('playerKey')}
    except Exception as e:
        logging.warning('shared_store read failed: %s', e)

    # FALLBACK: Original HTTP behavior
    port = os.environ.get('PORT')
    api_hostname = f'127.0.0.1:{port}'
    url = f"{scheme}://{api_hostname.rstrip('/')}{path if path.startswith('/') else '/' + path}"
    headers = {}
    env_user = get_env_secret('APP_USERNAME')
    env_pass = get_env_secret('APP_PASSWORD')
    if not username and env_user:
        username = env_user
    if not password and env_pass:
        password = env_pass
    auth_value = None
    if username and password:
        b64 = base64.b64encode(f"{username}:{password}".encode('utf-8')).decode('ascii')
        auth_value = f"Basic {b64}"
    if auth_value:
        headers['Authorization'] = auth_value

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, 'status', None) or getattr(resp, 'getcode', lambda: None)()
            if code and int(code) != 200:
                return {'changed': False}
            payload = json.loads(resp.read().decode('utf-8'))
            if not isinstance(payload, dict):
                return {'changed': False}

            info.update(_build_info_dict(payload))
            return {'changed': True}
    except Exception:
        pass
    return {'changed': False}
