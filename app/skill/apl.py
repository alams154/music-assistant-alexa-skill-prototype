# -*- coding: utf-8 -*-

import json
import logging
import os
import re
import sys
from urllib.parse import quote
from ask_sdk_model.interfaces.alexa.presentation.apl import RenderDocumentDirective
from ask_sdk_core.response_helper import ResponseFactory
from . import data

# Ensure /app/src is on the Python path so shared_store can be imported
_app_src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _app_src not in sys.path:
    sys.path.insert(0, _app_src)


def _load_apl_template():
    # type: () -> dict
    """Load the APL document template from JSON file."""
    template_path = os.path.join(os.path.dirname(__file__), 'apl_document.json')
    with open(template_path, 'r') as f:
        return json.load(f)


def add_apl(response_builder, start_paused=False):
    # type: (ResponseFactory, bool) -> None
    """Add the RenderDocumentDirective to the response with APL document."""
    # Import here to avoid circular imports
    from .util import rewrite_apl_image_url

    # Get metadata from shared_store (most reliable) or data.info as fallback
    metadata = _get_metadata()
    if not metadata:
        logging.warning("No metadata available for APL rendering")
        return

    cover_image = rewrite_apl_image_url(metadata.get("coverImageSource", ""))
    background_image = rewrite_apl_image_url(metadata.get("backgroundImageSource", ""))

    # Load the APL document template
    apl_document = _load_apl_template()

    # Set the dynamic autoplay value based on start_paused
    autoplay = not start_paused

    # Update autoplay in Video component and AlexaTransportControls
    try:
        video_component = apl_document["layouts"]["AudioPlayer"]["item"][0]["items"][2]["items"][1]["items"][0]
        video_component["autoplay"] = autoplay
    except (KeyError, IndexError):
        logging.debug("Could not set video autoplay in APL template")

    try:
        transport_controls = apl_document["layouts"]["AudioPlayer"]["item"][0]["items"][2]["items"][1]["items"][1]["items"][0]["item"][1]
        transport_controls["autoplay"] = autoplay
    except (KeyError, IndexError):
        logging.debug("Could not set transport autoplay in APL template")

    # Update mainTemplate with metadata values
    try:
        audio_sources = metadata.get("audioSources", "")
        if isinstance(audio_sources, str) and audio_sources:
            audio_sources = quote(audio_sources, safe=':/%?=&')
        main_template_item = apl_document["mainTemplate"]["items"][0]
        main_template_item.update({
            "audioSources": audio_sources,
            "backgroundImageSource": quote(background_image, safe=':/%?=&') if isinstance(background_image, str) and background_image else background_image,
            "coverImageSource": quote(cover_image, safe=':/%?=&') if isinstance(cover_image, str) and cover_image else cover_image,
            "headerAttributionImage": metadata.get("headerAttributionImage", ""),
            "headerTitle": metadata.get("headerTitle", ""),
            "headerSubtitle": metadata.get("headerSubtitle", ""),
            "primaryText": metadata.get("primaryText", ""),
            "secondaryText": metadata.get("secondaryText", "")
        })
    except (KeyError, IndexError):
        logging.warning("Could not update mainTemplate in APL document")

    response_builder.add_directive(
        RenderDocumentDirective(
            token="playbackToken",
            document=apl_document,
            datasources={}
        )
    )


def _get_metadata():
    """Get metadata from shared_store or data.info.

    shared_store is the primary source (set by MA push-url).
    data.info is the fallback (set by data.get_latest()).
    """
    # Priority 1: shared_store (most reliable, set by MA)
    try:
        import shared_store
        if shared_store._store:
            store = shared_store._store
            stream_url = store.get("streamUrl", "") or ""
            if isinstance(stream_url, str) and stream_url:
                stream_url = re.sub(r'(?i)\.flac(?=$|\?)', '.mp3', stream_url)
            return {
                "audioSources": stream_url,
                "backgroundImageSource": store.get("imageUrl", ""),
                "coverImageSource": store.get("imageUrl", ""),
                "headerAttributionImage": "",
                "headerTitle": "",
                "headerSubtitle": "",
                "primaryText": store.get("title", ""),
                "secondaryText": _build_secondary_text(store)
            }
    except Exception as e:
        logging.debug("shared_store read failed in APL: %s", e)

    # Priority 2: data.info (fallback)
    try:
        if data.info and data.info.get("audioSources"):
            return data.info
    except Exception:
        pass

    return None


def _build_secondary_text(store):
    """Build secondary text from artist and album."""
    artist = store.get("artist", "")
    album = store.get("album", "")
    if artist and album:
        return f"{artist} - {album}"
    elif artist:
        return artist
    elif album:
        return album
    return ""
