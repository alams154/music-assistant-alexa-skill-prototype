# -*- coding: utf-8 -*-
import gettext

_ = gettext.gettext

import json
import os
import logging
from typing import Optional

import urllib.request
import urllib.error

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


en = {
    "url": 'https://streams.80s80s.de/web/mp3-192/streams.80s80s.de',
    "audioSources": 'https://streams.80s80s.de/web/mp3-192/streams.80s80s.de',
    "backgroundImageSource": "https://d2o906d8ln7ui1.cloudfront.net/images/response_builder/background-rose.png",
    "coverImageSource": "https://d2o906d8ln7ui1.cloudfront.net/images/response_builder/card-rose.jpeg",
    "headerAttributionImage": "",
    "headerTitle": "title", # Music Assistant
    "headerSubtitle": "subtitle", # Media Type
    "primaryText": "prime", # Song Title
    "secondaryText": "second", # Artist Name + Album Name
    "sliderType": "determinate"
}

def get_latest(hostname: Optional[str] = None,
               path: str = '/ma/latest-url',
               scheme: str = 'http',
               timeout: int = 5) -> dict:
    """Fetch latest stream info from music-assistant API and map to APL fields.

    Expected JSON shape: {"streamUrl":..., "title":..., "artist":..., "album":..., "imageUrl":...}
    Returns a dict with APL-friendly keys. If the API cannot be reached or
    returns unexpected data, the function returns the expected keys with
    empty-string defaults.
    """
    if hostname is None:
        hostname = os.environ.get('DATA_API_HOST')
    if not hostname:
        logging.debug('No hostname provided for get_latest and DATA_API_HOST unset.')
        return {
            'audioSources': '',
            'backgroundImageSource': '',
            'coverImageSource': '',
            'headerAttributionImage': '',
            'headerTitle': '',
            'headerSubtitle': '',
            'primaryText': '',
            'secondaryText': '',
            'sliderType': 'determinate'
        }

    url = f"{scheme}://{hostname.rstrip('/')}{path if path.startswith('/') else '/' + path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            code = getattr(resp, 'status', None) or getattr(resp, 'getcode', lambda: None)()
            if code and int(code) != 200:
                logging.warning('Request to %s returned status %s', url, code)
                return {
                    'audioSources': '',
                    'backgroundImageSource': '',
                    'coverImageSource': '',
                    'headerAttributionImage': '',
                    'headerTitle': '',
                    'headerSubtitle': '',
                    'primaryText': '',
                    'secondaryText': '',
                    'sliderType': 'determinate'
                }
            payload = json.loads(resp.read().decode('utf-8'))
            if not isinstance(payload, dict):
                logging.warning('Unexpected payload shape from %s', url)
                return {
                    'audioSources': '',
                    'backgroundImageSource': '',
                    'coverImageSource': '',
                    'headerAttributionImage': '',
                    'headerTitle': '',
                    'headerSubtitle': '',
                    'primaryText': '',
                    'secondaryText': '',
                    'sliderType': 'determinate'
                }

            stream_url = payload.get('streamUrl') or payload.get('stream_url') or ''
            title = payload.get('title', '') or ''
            artist = payload.get('artist', '') or ''
            album = payload.get('album', '') or ''
            image = payload.get('imageUrl') or payload.get('image_url') or ''

            secondary = ''
            if artist and album:
                secondary = f"{artist} - {album}"
            elif artist:
                secondary = artist
            elif album:
                secondary = album

            return {
                'audioSources': stream_url,
                'backgroundImageSource': image,
                'coverImageSource': image,
                'headerAttributionImage': '',
                'headerTitle': '',
                'headerSubtitle': '',
                'primaryText': title,
                'secondaryText': secondary,
                'sliderType': 'determinate'
            }
    except urllib.error.URLError as e:
        logging.warning('Could not reach %s: %s', url, e)
    except Exception:
        logging.exception('Error while loading latest data from %s', url)

    return {
        'audioSources': '',
        'backgroundImageSource': '',
        'coverImageSource': '',
        'headerAttributionImage': '',
        'headerTitle': '',
        'headerSubtitle': '',
        'primaryText': '',
        'secondaryText': '',
        'sliderType': 'determinate'
    }