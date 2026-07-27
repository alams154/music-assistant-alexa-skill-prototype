# -*- coding: utf-8 -*-
"""Send player commands to Music Assistant via music_assistant_client.

Only used for commands that are safe to route through MA's own player
command API. Pause/Stop/Resume are deliberately NOT sent through here:
for the `alexa` MA player provider, those commands are implemented by
speaking the corresponding phrase back into the device via alexapy,
which would re-trigger the same Alexa intent on this skill and loop.
Next/Previous/StartOver are safe because MA handles them at the queue
level and reacts by pushing new content via /ma/push-url instead of
speaking a command-like phrase.
"""

import asyncio
import logging

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

SUPPORTED_COMMANDS = ("next", "previous", "start_over")


async def _play_relative_index(client, player_id, offset):
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
    target_index = max(queue.current_index + offset, 0)
    await client.player_queues.play_index(queue.queue_id, target_index)


async def _send_command(server_url, token, player_id, command):
    async with aiohttp.ClientSession() as session:
        async with MusicAssistantClient(server_url, session, token=token) as client:
            if command == "next":
                await client.players.next_track(player_id)
            elif command == "previous":
                await _play_relative_index(client, player_id, -1)
            elif command == "start_over":
                await _play_relative_index(client, player_id, 0)
            else:
                raise ValueError(f"Unsupported MA command: {command}")


def send_player_command(player_id, command):
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
        asyncio.run(_send_command(server_url, token, player_id, command))
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
