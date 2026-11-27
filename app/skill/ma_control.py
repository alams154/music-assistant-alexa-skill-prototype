# -*- coding: utf-8 -*-
"""Send player commands to Music Assistant via music_assistant_client.

Next/Previous/StartOver are safe to send unconditionally: MA handles them
at the queue level and reacts by pushing new content via /ma/push-url,
not by speaking a command-like phrase.

Pause/Stop/Resume are different: the `alexa` MA player provider
implements them by speaking the corresponding phrase back into the
device via alexapy (Alexa.TextCommand - a direct API call, not TTS
through the speaker, so it reliably re-triggers a real intent request).
That would loop back into this same skill. Callers MUST use
mark_ma_triggered()/is_echo_of_ma_command() to suppress exactly the
one echoed intent this causes, rather than calling send_player_command
for these unconditionally.
"""

import asyncio
import logging
import threading
import time

import aiohttp
from music_assistant_client import MusicAssistantClient
from music_assistant_client.exceptions import (
    CannotConnect,
    ConnectionFailed,
    InvalidServerVersion,
)
from music_assistant_models.errors import MusicAssistantError

from env_secrets import get_env_secret

logger = logging.getLogger(__name__)

SUPPORTED_COMMANDS = ("next", "previous", "start_over", "pause", "stop", "resume")

# How long to suppress the echoed intent caused by pause/stop/resume.
# Alexa.TextCommand is a direct API call (not acoustic), so the round trip
# is consistently fast; this just needs to comfortably cover it.
_ECHO_SUPPRESS_SECONDS = 8
_recent_ma_triggered = {}
_recent_lock = threading.Lock()


def mark_ma_triggered(device_id, command):
    """Record that we're about to send `command` to MA for device_id.

    Call this immediately before send_player_command() for pause/stop/resume,
    so the intent MA's alexa provider echoes back gets recognized and not
    re-forwarded to MA again.
    """
    if not device_id:
        return
    with _recent_lock:
        _recent_ma_triggered[(device_id, command)] = time.time() + _ECHO_SUPPRESS_SECONDS


def is_echo_of_ma_command(device_id, command):
    """Check (and consume) whether this looks like the echo of our own MA command."""
    if not device_id:
        return False
    key = (device_id, command)
    with _recent_lock:
        expires_at = _recent_ma_triggered.pop(key, None)
    return expires_at is not None and expires_at >= time.time()


async def _play_relative_index(client, player_id, offset, ref_item_id=None):
    """Jump the active queue to current_index + offset (clamped to 0).

    MA's own queue/cmd/previous restarts the current track instead of
    going to the prior one once more than 5s have elapsed - always true
    for voice-triggered commands. Fetching the queue and calling
    play_index directly bypasses that heuristic. offset=0 restarts the
    current track (used for AMAZON.StartOverIntent).
    """
    queue = await client.player_queues.get_active_queue(player_id)
    if queue is None or queue.current_index is None:
        raise ValueError(f"No active queue/current track for player {player_id}")
    base_index = queue.current_index
    # Start from the track shown on the screen; in flow mode MA's
    # current_index can already point at the next track.
    if ref_item_id:
        try:
            first = max(0, base_index - 25)
            items = await client.player_queues.get_queue_items(queue.queue_id, limit=50, offset=first)
            for i, it in enumerate(items):
                if it.queue_item_id == ref_item_id:
                    base_index = first + i
                    break
        except Exception:
            logger.debug("Could not read the queue items", exc_info=True)
    target_index = max(base_index + offset, 0)
    logger.info("MA queue %s: shown track index %s (MA current_index %s, %s items) -> play index %s",
                queue.queue_id, base_index, queue.current_index, getattr(queue, 'items', '?'), target_index)
    if base_index + offset < 0:
        logger.info("Nothing before this track in the MA queue: restarting it")
    await client.player_queues.play_index(queue.queue_id, target_index)


async def _send_command(server_url, token, player_id, command, ref_item_id=None):
    async with aiohttp.ClientSession() as session:
        async with MusicAssistantClient(server_url, session, token=token) as client:
            if command == "next":
                await client.players.next_track(player_id)
            elif command == "previous":
                await _play_relative_index(client, player_id, -1, ref_item_id)
            elif command == "start_over":
                await _play_relative_index(client, player_id, 0, ref_item_id)
            elif command == "pause":
                await client.players.pause(player_id)
            elif command == "stop":
                await client.players.stop(player_id)
            elif command == "resume":
                # Not players.resume(): the alexa provider only overrides
                # play(), which is what speaks the AMAZON.ResumeIntent
                # utterance back into the device.
                await client.players.play(player_id)
            else:
                raise ValueError(f"Unsupported MA command: {command}")


def send_player_command(player_id, command, ref_item_id=None):
    """Send a command to a Music Assistant player. Returns True on success.

    This opens a short-lived connection per call; commands are infrequent
    (voice-triggered), so the connection overhead is not a concern here.
    """
    if command not in SUPPORTED_COMMANDS:
        raise ValueError(f"Unsupported MA command: {command}")

    server_url = get_env_secret("MA_API_URL")
    token = get_env_secret("MA_API_TOKEN")

    if not server_url:
        logger.error("MA_API_URL is not set; cannot send %s command to MA", command)
        return False

    try:
        asyncio.run(_send_command(server_url, token, player_id, command, ref_item_id))
        return True
    except (CannotConnect, ConnectionFailed, InvalidServerVersion) as e:
        logger.error("Could not connect to Music Assistant at %s: %s", server_url, e)
        return False
    except MusicAssistantError as e:
        logger.error("Music Assistant rejected %s command for player %s: %s", command, player_id, e)
        return False
    except Exception:
        logger.exception("Unexpected error sending %s command to MA player %s", command, player_id)
        return False



# Current track of a player, read from Music Assistant.
async def _get_now_playing(server_url, token, player_id):
    async with aiohttp.ClientSession() as session:
        async with MusicAssistantClient(server_url, session, token=token) as client:
            queue = await client.player_queues.get_active_queue(player_id)
            item = queue.current_item if queue else None
            if item is None:
                return None
            media = item.media_item
            title = (getattr(media, "name", None) or item.name or "")
            artists = getattr(media, "artists", None) or []
            artist = "/".join(a.name for a in artists if getattr(a, "name", None))
            album_obj = getattr(media, "album", None)
            album = getattr(album_obj, "name", "") or ""
            image = ""
            try:
                image = client.get_media_item_image_url(item) or ""
            except Exception:
                image = ""
            import time as _time
            elapsed = float(getattr(queue, "elapsed_time", 0) or 0)
            updated = getattr(queue, "elapsed_time_last_updated", None)
            state = getattr(queue, "state", "")
            state = str(getattr(state, "value", state) or "").lower()
            if updated and state == "playing":
                elapsed += max(0.0, _time.time() - float(updated))
            duration = float(item.duration or 0)
            return {"queue_item_id": item.queue_item_id, "title": title,
                    "artist": artist, "album": album, "imageUrl": image,
                    "elapsed_ms": int(elapsed * 1000),
                    "duration_ms": int(duration * 1000)}


def get_now_playing(player_id):
    """Return {queue_item_id, title, artist, album, imageUrl} or None."""
    server_url = get_env_secret("MA_API_URL")
    token = get_env_secret("MA_API_TOKEN")
    if not server_url or not player_id:
        return None
    try:
        return asyncio.run(_get_now_playing(server_url, token, player_id))
    except Exception:
        logger.debug("get_now_playing failed for %s", player_id, exc_info=True)
        return None


# Seek the active queue of a player (position in seconds in the current track).
async def _seek(server_url, token, player_id, seconds):
    async with aiohttp.ClientSession() as session:
        async with MusicAssistantClient(server_url, session, token=token) as client:
            queue = await client.player_queues.get_active_queue(player_id)
            if queue is None:
                raise ValueError(f"No active queue for player {player_id}")
            await client.player_queues.seek(queue.queue_id, int(seconds))


def seek_player(player_id, seconds):
    server_url = get_env_secret("MA_API_URL")
    token = get_env_secret("MA_API_TOKEN")
    if not server_url or not player_id:
        return False
    try:
        asyncio.run(_seek(server_url, token, player_id, max(0, seconds)))
        return True
    except Exception:
        logger.exception("Seek to %ss failed for MA player %s", seconds, player_id)
        return False


# Playback state of the active queue of a player ("playing", "paused", ...).
async def _get_queue_state(server_url, token, player_id):
    async with aiohttp.ClientSession() as session:
        async with MusicAssistantClient(server_url, session, token=token) as client:
            queue = await client.player_queues.get_active_queue(player_id)
            if queue is None:
                return None
            state = getattr(queue, "state", "")
            return str(getattr(state, "value", state) or "").lower()


def get_queue_state(player_id):
    server_url = get_env_secret("MA_API_URL")
    token = get_env_secret("MA_API_TOKEN")
    if not server_url or not player_id:
        return None
    try:
        return asyncio.run(_get_queue_state(server_url, token, player_id))
    except Exception:
        logger.debug("get_queue_state failed for %s", player_id, exc_info=True)
        return None
