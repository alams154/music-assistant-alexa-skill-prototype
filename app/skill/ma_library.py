import asyncio
import os
from typing import Any, Dict, List

from music_assistant_client import MusicAssistantClient
from music_assistant_models.enums import MediaType

MA_BASE_URL = os.environ.get("MA_BASE_URL", "").rstrip("/")
MA_TOKEN = os.environ.get("MA_TOKEN", "")

if not MA_BASE_URL:
    raise RuntimeError("MA_BASE_URL is not set")
if not MA_TOKEN:
    raise RuntimeError("MA_TOKEN is not set")


async def _fetch_tracks_by_artist_async(artist_name: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Return [{"title":..., "artist":..., "url":...}] from MA local library."""
    async with MusicAssistantClient(MA_BASE_URL, None, token=MA_TOKEN) as client:
        results = await client.music.search(
            search_query=artist_name,
            media_types=[MediaType.ARTIST],
            limit=10,
            library_only=True,
        )

        # Some versions return dict, others return object with attributes
        if isinstance(results, dict):
            artists = results.get("artists") or results.get(MediaType.ARTIST) or []
        else:
            artists = getattr(results, "artists", []) or []

        if not artists:
            return []

        artist = artists[0]
        artist_id = getattr(artist, "item_id", None) or getattr(artist, "id", None)
        if not artist_id:
            return []

        tracks = await client.music.get_artist_tracks(artist_id, limit=limit)

        out: List[Dict[str, Any]] = []
        for tr in tracks:
            track_id = getattr(tr, "item_id", None) or getattr(tr, "id", None)
            if not track_id:
                continue

            # stable, directly playable URL
            url = await client.music.get_track_preview_url(track_id)
            if not url:
                continue

            title = getattr(tr, "name", None) or getattr(tr, "title", None) or "Unknown title"
            artist_str = artist_name
            artists_attr = getattr(tr, "artists", None)
            if artists_attr and isinstance(artists_attr, list) and len(artists_attr) > 0:
                artist_str = getattr(artists_attr[0], "name", artist_name) or artist_name

            out.append({"title": title, "artist": artist_str, "url": url})

        return out


def fetch_tracks_by_artist(artist_name: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Sync wrapper for ASK handlers."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(_fetch_tracks_by_artist_async(artist_name, limit=limit))
        finally:
            new_loop.close()
    else:
        return asyncio.run(_fetch_tracks_by_artist_async(artist_name, limit=limit))
