# -*- coding: utf-8 -*-

import json
import logging
import os
from ask_sdk_model.interfaces.alexa.presentation.apl import RenderDocumentDirective
from ask_sdk_core.response_helper import ResponseFactory
from . import data


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
    from .util import get_ma_hostname, replace_ip_in_url
    
    # Replace MA-hosted image sources if MA_HOSTNAME is set.
    try:
        hostname = get_ma_hostname(raise_on_http_scheme=False)
    except ValueError:
        hostname = ''

    if hostname:
        data.info["coverImageSource"] = replace_ip_in_url(data.info.get("coverImageSource", ""), hostname)

    # Load the APL document template
    apl_document = _load_apl_template()

    # Set the dynamic autoplay value based on start_paused
    autoplay = not start_paused
    
    # Update autoplay in Video component and AlexaTransportControls
    video_component = apl_document["layouts"]["AudioPlayer"]["item"][0]["items"][2]["items"][1]["items"][0]
    video_component["autoplay"] = autoplay
    
    transport_controls = apl_document["layouts"]["AudioPlayer"]["item"][0]["items"][2]["items"][1]["items"][1]["items"][0]["item"][1]
    transport_controls["autoplay"] = autoplay

    # Update mainTemplate with data.info values
    main_template_item = apl_document["mainTemplate"]["items"][0]
    main_template_item.update({
        "audioSources": data.info["audioSources"],
        "backgroundImageSource": data.info["backgroundImageSource"],
        "coverImageSource": data.info["coverImageSource"],
        "headerAttributionImage": data.info["headerAttributionImage"],
        "headerTitle": data.info["headerTitle"],
        "headerSubtitle": data.info["headerSubtitle"],
        "primaryText": data.info["primaryText"],
        "secondaryText": data.info["secondaryText"]
    })

    response_builder.add_directive(
        RenderDocumentDirective(
            token="playbackToken",
            document=apl_document,
            datasources={}
        )
    )
