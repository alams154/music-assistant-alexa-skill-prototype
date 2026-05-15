# -*- coding: utf-8 -*-
import gettext
_ = gettext.gettext

import json
import os
import sys
import logging
from typing import Optional
from env_secrets import get_env_secret
import urllib.request
import urllib.error
import base64
import re

# Ensure /app/src is on the Python path so shared_store can be imported
# when this module is loaded from /app/src/skill/
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

_last_version = None


def get_latest(api_hostname: Optional[str] = None,
               path: str = '/ma/latest-url',
               scheme: str = 'http',
               timeout: int = 5,
               username: Optional[str] = None,
               password: Optional[str] = None) -> dict:
    """Fetch latest stream info from music-assistant API and map to APL fields.

    Expected JSON shape: {"streamUrl":..., "title":..., "artist":..., 
    "album":..., "imageUrl":..., "version":..., "timestamp":...}

    Returns a dict with 'changed': bool indicating if the data actually changed.
    """
    global info, _last_version

    # PRIORITY 1: Read directly from shared_store (fast, no HTTP overhead)
    try:
        import shared_store
        if shared_store._store and shared_store._store.get('streamUrl'):
            payload = shared_store._store
            current_version = payload.get('version')
            if current_version is not None and current_version == _last_version:
                logging.debug(f"Data version {current_version} unchanged (shared_store), skipping update")
                return {'changed': False}

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

            # Rewrite FLAC to MP3 for broader Echo device compatibility
            if stream_url and isinstance(stream_url, str):
                try:
                    stream_url = re.sub(r'(?i)\.flac(?=$|\?)', '.mp3', stream_url)
                except Exception:
                    logging.exception('Failed rewriting stream URL extension for %s', stream_url)

            info.update({
                'audioSources': stream_url,
                'backgroundImageSource': image,
                'coverImageSource': image,
                'headerAttributionImage': '',
                'headerTitle': '',
                'headerSubtitle': '',
                'primaryText': title,
                'secondaryText': secondary
            })

            if current_version is not None:
                _last_version = current_version

            logging.info('Loaded stream data from shared_store: %s', title)
            return {'changed': True}
    except Exception as e:
        logging.debug('shared_store read failed, falling back to HTTP: %s', e)

    # FALLBACK: Original HTTP behavior (for backward compatibility)
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
                logging.warning('Request to %s returned status %s', url, code)
                return {'changed': False}
            payload = json.loads(resp.read().decode('utf-8'))
            if not isinstance(payload, dict):
                logging.warning('Unexpected payload shape from %s', url)
                return {'changed': False}

            current_version = payload.get('version')
            if current_version is not None and current_version == _last_version:
                logging.debug(f"Data version {current_version} unchanged, skipping update")
                return {'changed': False}

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
                except Exception:
                    logging.exception('Failed rewriting stream URL extension for %s', stream_url)

            info.update({
                'audioSources': stream_url,
                'backgroundImageSource': image,
                'coverImageSource': image,
                'headerAttributionImage': '',
                'headerTitle': '',
                'headerSubtitle': '',
                'primaryText': title,
                'secondaryText': secondary
            })

            if current_version is not None:
                _last_version = current_version

            return {'changed': True}
    except urllib.error.URLError as e:
        logging.warning('Could not reach %s: %s', url, e)
    except Exception:
        logging.exception('Error while loading latest data from %s', url)
    return {'changed': False}
