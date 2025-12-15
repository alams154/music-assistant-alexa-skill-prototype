# -*- coding: utf-8 -*-
import gettext

_ = gettext.gettext

import json
import os
import logging
from typing import Optional

import urllib.request
import urllib.error
import base64
import re

WELCOME_MSG = _("")
HELP_MSG = _("Welcome to {}. You can play, stop, resume listening.  How can I help you ?")
UNHANDLED_MSG = _("Sorry, I could not understand what you've just said.")
CANNOT_SKIP_MSG = _("This is radio, you have to wait for previous or next track to play.")
RESUME_MSG = _("Resuming {}")
NOT_POSSIBLE_MSG = _("This is radio, you can not do that.  You can ask me to stop or pause to stop listening.")
STOP_MSG = _("Goodbye.")
DEVICE_NOT_SUPPORTED = _("Sorry, this skill is not supported on this device")

TEST = _("test english")
TEST_PARAMS = _("test with parameters {} and {}")


# en = {
#     "url": 'https://streams.80s80s.de/web/mp3-192/streams.80s80s.de',
#     "audioSources": 'https://streams.80s80s.de/web/mp3-192/streams.80s80s.de',
#     "backgroundImageSource": "https://d2o906d8ln7ui1.cloudfront.net/images/response_builder/background-rose.png",
#     "coverImageSource": "https://d2o906d8ln7ui1.cloudfront.net/images/response_builder/card-rose.jpeg",
#     "headerAttributionImage": "",
#     "headerTitle": "title", # Music Assistant
#     "headerSubtitle": "subtitle", # Media Type
#     "primaryText": "prime", # Song Title
#     "secondaryText": "second", # Artist Name + Album Name
#     "sliderType": "determinate"
# }

test = {
            "audioSources": "",
            "backgroundImageSource": "",
            "coverImageSource": "",
            "headerAttributionImage": "",
            "headerTitle": "",
            "headerSubtitle": "",
            "primaryText": "",
            "secondaryText": ""
}

def get_latest(api_hostname: Optional[str] = None,
               ma_hostname: Optional[str] = None,
               path: str = '/ma/latest-url',
               scheme: str = 'http',
               timeout: int = 5,
               username: Optional[str] = None,
               password: Optional[str] = None,
               auth_header: Optional[str] = None) -> dict:
    """Fetch latest stream info from music-assistant API and map to APL fields.

    Expected JSON shape: {"streamUrl":..., "title":..., "artist":..., "album":..., "imageUrl":...}
    Returns a dict with APL-friendly keys. If the API cannot be reached or
    returns unexpected data, the function returns the expected keys with
    empty-string defaults.
    """
    global test

    if api_hostname is None:
        api_hostname = os.environ.get('API_HOSTNAME')
    if not api_hostname:
        logging.debug('No api_hostname provided for get_latest and API_HOSTNAME unset.')
        return
    
    if ma_hostname is None:
        ma_hostname = os.environ.get('MA_HOSTNAME')
    if not ma_hostname:
        logging.debug('No ma_hostname provided for get_latest and MA_HOSTNAME unset.')
        return

    url = f"{scheme}://{api_hostname.rstrip('/')}{path if path.startswith('/') else '/' + path}"
    # Prepare Authorization header if credentials provided (params or env)
    headers = {}
    # Priority: explicit auth_header param -> API_BASIC_AUTH env -> username/password params -> API_USERNAME/API_PASSWORD env
    if not auth_header:
        auth_header = os.environ.get('API_BASIC_AUTH')

    env_user = os.environ.get('API_USERNAME')
    env_pass = os.environ.get('API_PASSWORD')
    if not username and env_user:
        username = env_user
    if not password and env_pass:
        password = env_pass

    # If auth_header looks like 'user:pass' (no 'Basic '), convert to Basic
    auth_value = None
    if auth_header:
        if ':' in auth_header and ' ' not in auth_header:
            u, p = auth_header.split(':', 1)
            b64 = base64.b64encode(f"{u}:{p}".encode('utf-8')).decode('ascii')
            auth_value = f"Basic {b64}"
        else:
            auth_value = auth_header if auth_header.lower().startswith('basic ') else f"Basic {auth_header}"
    elif username and password:
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
                return
            payload = json.loads(resp.read().decode('utf-8'))
            if not isinstance(payload, dict):
                logging.warning('Unexpected payload shape from %s', url)
                return

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

            # Rewrite stream host to MA host if provided (ma_hostname param or MA_HOSTNAME env)
            if stream_url:
                target_host = ma_hostname or os.environ.get('MA_HOSTNAME')
                if target_host:
                    try:
                        # strip any scheme and trailing slash from provided host
                        target_host = re.sub(r'^https?:\/\/', '', str(target_host)).rstrip('/')
                        # replace original scheme+host with https://{target_host}
                        stream_url = re.sub(r'^https?:\/\/[^\/]+', f'https://{target_host}', stream_url)
                    except Exception:
                        logging.exception('Failed rewriting stream URL host for %s', stream_url)

            # # Rewrite image host to MA host if provided (ma_hostname param or MA_HOSTNAME env)
            # if image:
            #     target_host = ma_hostname or os.environ.get('MA_HOSTNAME')
            #     if target_host:
            #         try:
            #             # strip any scheme and trailing slash from provided host
            #             target_host = re.sub(r'^https?:\/\/', '', str(target_host)).rstrip('/')
            #             # replace original scheme+host with https://{target_host}
            #             image = re.sub(r'^https?:\/\/[^\/]+', f'https://{target_host}', image)
            #         except Exception:
            #             logging.exception('Failed rewriting image URL host for %s', image)

            test.update({
                'audioSources': stream_url,
                'backgroundImageSource': image,
                'coverImageSource': image,
                'headerAttributionImage': '',
                'headerTitle': '',
                'headerSubtitle': '',
                'primaryText': title,
                'secondaryText': secondary
            })
            return
    except urllib.error.URLError as e:
        logging.warning('Could not reach %s: %s', url, e)
    except Exception:
        logging.exception('Error while loading latest data from %s', url)
    return