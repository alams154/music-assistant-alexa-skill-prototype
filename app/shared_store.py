"""Shared store for MA and Alexa routes."""

_store = None
_version = 0


# State shared between the MA API and the skill.
import threading as _threading
import time as _time

LIVE_PAGE_TIMEOUT = 6          # seconds without APL refresh -> screen considered closed
_live_lock = _threading.Lock()
_live_pages = {}               # player_id -> time of the last APL refresh
_pending = {}                  # player_id -> ["stream" | "pause" | "resume", ...]
_rendered_stream = {}          # player_id -> stream URL shown on the open screen
_reports = {}                  # player_id -> {activity, offsetMs, observedAt, streamUrl}


def page_live(player_id):
    if not player_id:
        return False
    with _live_lock:
        return _time.time() - _live_pages.get(player_id, 0) < LIVE_PAGE_TIMEOUT


def mark_page_live(player_id):
    with _live_lock:
        _live_pages[player_id] = _time.time()


def add_pending(player_id, action):
    with _live_lock:
        _pending.setdefault(player_id, []).append(action)


def pop_pending(player_id):
    with _live_lock:
        return _pending.pop(player_id, [])


def set_report(player_id, activity, offset_ms, stream_url, observed_at=None):
    with _live_lock:
        _reports[player_id] = {"activity": activity, "offsetMs": int(offset_ms),
                               "observedAt": observed_at or _time.time(), "streamUrl": stream_url}


def get_report(player_id):
    with _live_lock:
        r = _reports.get(player_id)
        return dict(r) if r else None


def stream_key(url):
    """Identity of a stream URL: its path, decoded, without the extension."""
    if not url:
        return None
    from urllib.parse import urlparse, unquote
    path = unquote(urlparse(str(url)).path or "")
    head, dot, ext = path.rpartition(".")
    return head if dot and "/" not in ext else path


# One "now playing" per Music Assistant player.
# shared_store._store reads/writes the entry of the player tied to the current
# request (set_request_player), or the latest entry when none is known.
import sys as _sys
import types as _types

_request = _threading.local()
_by_player = {}
_latest = globals().pop("_store", None)


def set_request_player(player_id):
    _request.player = player_id or None


def request_player():
    return getattr(_request, "player", None)


def store_for(player_id):
    with _live_lock:
        if player_id and player_id in _by_player:
            return _by_player[player_id]
        return _latest


class _StoreModule(_types.ModuleType):
    @property
    def _store(self):
        return store_for(request_player())

    @_store.setter
    def _store(self, value):
        global _latest
        player = request_player()
        with _live_lock:
            if player:
                _by_player[player] = value
            _latest = value


_sys.modules[__name__].__class__ = _StoreModule
