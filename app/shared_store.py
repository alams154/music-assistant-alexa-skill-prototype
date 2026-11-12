"""Thread-safe shared store with per-player isolation for MA and Alexa routes."""

import re
import threading
import time
from urllib.parse import unquote, urlsplit

_lock = threading.Lock()
_store = None
_version = 0
_by_player = {}
_device_players = {}

_EXT_RE = re.compile(r'\.(?:flac|mp3|aac|m4a|wav|ogg|opus)$', re.IGNORECASE)


def extract_player_key(stream_url):
    """Extract MA player_id from a stream URL path such as /flow/<sid>/<queue>/<item>/<player>.mp3."""
    if not stream_url or not isinstance(stream_url, str):
        return None
    try:
        parts = [p for p in urlsplit(stream_url).path.split('/') if p]
        if not parts:
            return None
        candidate = unquote(parts[-1]).strip()
        candidate = _EXT_RE.sub('', candidate).strip()
        return candidate or None
    except Exception:
        return None


def put_ma_stream(stream_url, title=None, artist=None, album=None, image_url=None):
    """Store an incoming MA stream payload globally and indexed by its player key."""
    global _store, _version
    player_key = extract_player_key(stream_url)
    with _lock:
        _version += 1
        entry = {
            'streamUrl': stream_url,
            'title': title,
            'artist': artist,
            'album': album,
            'imageUrl': image_url,
            'playerKey': player_key,
            'version': _version,
            'timestamp': time.time(),
        }
        _store = entry
        if player_key:
            _by_player[player_key] = entry
        return _version, player_key


def bind_device_player(device_id, player_key):
    """Associate an Alexa device_id with the MA player_key it just began playing."""
    if not device_id or not player_key:
        return
    with _lock:
        _device_players[device_id] = player_key


def get_ma_stream(device_id=None, mapped_player=None, prefer_latest=False):
    """Resolve the active stream entry for an Alexa device, with safe fallbacks."""
    with _lock:
        if mapped_player and mapped_player in _by_player:
            return dict(_by_player[mapped_player])
        if prefer_latest and _store:
            return dict(_store)
        if device_id:
            pk = _device_players.get(device_id)
            if pk and pk in _by_player:
                return dict(_by_player[pk])
        return dict(_store) if _store else None
