# -*- coding: utf-8 -*-

import datetime
from typing import Dict, Optional
from ask_sdk_model import Request, Response
from ask_sdk_model.ui import StandardCard, Image
from ask_sdk_model.interfaces.audioplayer import (
    PlayDirective, PlayBehavior, AudioItem, Stream, AudioItemMetadata,
    StopDirective, ClearQueueDirective, ClearBehavior)
from ask_sdk_model.interfaces import display
from ask_sdk_core.response_helper import ResponseFactory
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model.interfaces.alexa.presentation.apl import RenderDocumentDirective
from . import data

def audio_data(request):
    # type: (Request) -> Dict
    default_locale = "en-US"
    if request.locale is None:
        locale = default_locale
    else:
        locale = request.locale

    if locale.startswith("en"):
        test = data.en
        test["card"]["large_image_url"] = "https://raw.githubusercontent.com/music-assistant/server/refs/heads/dev/music_assistant/logo.png"
        test["card"]["small_image_url"] = "https://raw.githubusercontent.com/music-assistant/server/refs/heads/dev/music_assistant/logo.png"
        return test
    elif locale.startswith("fr"):
        return data.fr
    elif locale.startswith("it"):
        return data.it
    elif locale.startswith("es"):
        return data.es
    else:
        return {}


def play(url, offset, text, card_data, response_builder, supports_apl=False):
    """Function to play audio.

    Using the function to begin playing audio when:
        - Play Audio Intent is invoked.
        - Resuming audio when stopped / paused.
        - Next / Previous commands issues.

    https://developer.amazon.com/docs/custom-skills/audioplayer-interface-reference.html#play
    REPLACE_ALL: Immediately begin playback of the specified stream,
    and replace current and enqueued streams.
    """
    # type: (str, int, str, Dict, ResponseFactory) -> Response

    # Using URL as token as they are all unique
    response_builder.add_directive(
        PlayDirective(
            play_behavior=PlayBehavior.REPLACE_ALL,
            audio_item=AudioItem(
                stream=Stream(
                    token=url,
                    url=url,
                    offset_in_milliseconds=offset,
                    expected_previous_token=None),
                metadata=add_screen_background(card_data) if card_data else None
            )
        )
    ).set_should_end_session(True)

    add_apl(response_builder) if supports_apl else None

    if text:
        response_builder.speak(text)

    return response_builder.response


def stop(text, response_builder):
    """Issue stop directive to stop the audio.

    Issuing AudioPlayer.Stop directive to stop the audio.
    Attributes already stored when AudioPlayer.Stopped request received.
    """
    # type: (str, ResponseFactory) -> Response
    response_builder.add_directive(StopDirective())
    if text:
        response_builder.speak(text)

    return response_builder.response

def clear(response_builder):
    """Clear the queue and stop the player."""
    # type: (ResponseFactory) -> Response
    response_builder.add_directive(ClearQueueDirective(
        clear_behavior=ClearBehavior.CLEAR_ENQUEUED))
    return response_builder.response

def add_screen_background(card_data):
    # type: (Dict) -> Optional[AudioItemMetadata]
    if card_data:
        metadata = AudioItemMetadata(
            title=card_data["title"],
            subtitle=card_data["text"],
            art=display.Image(
                content_description=card_data["title"],
                sources=[
                    display.ImageInstance(
                        url=data.en["card"]["large_image_url"])
                ]
            )
            , background_image=display.Image(
                content_description=card_data["title"],
                sources=[
                    display.ImageInstance(
                        url=data.en["card"]["small_image_url"])
                ]
            )
        )
        return metadata
    else:
        return None

def add_apl(response_builder):
    """Add the RenderDocumentDirective"""
    # apl_document = {
    #     "type": "APL",
    #     "version": "2024.3.0",
    #     "mainTemplate": {
    #         "items": [
    #             {
    #                 "type": "Container",
    #                 "alignItems": "center",
    #                 "items": [
    #                     {
    #                         "type": "Text",
    #                         "text": "Now Playing",
    #                         "textAlign": "center",
    #                         "textAlignVertical": "center"
    #                     },
    #                     {
    #                         "type": "Image",
    #                         "source": "https://raw.githubusercontent.com/music-assistant/server/refs/heads/dev/music_assistant/logo.png",
    #                         "scale": "best-fill",
    #                     }
    #                 ]
    #             }
    #         ]
    #     }
    # }
    apl_document = {
        "type": "APL",
        "version": "2024.3",
        "license": "Copyright 2024 Amazon.com, Inc. or its affiliates. All Rights Reserved.\nSPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0\nLicensed under the Amazon Software License  http://aws.amazon.com/asl/",
        "theme": "dark",
        "import": [
            {
                "name": "alexa-layouts",
                "version": "1.7.0"
            }
        ],
        "resources": [
            {
                "description": "Default resource definitions for Audio template",
                "colors": {
                    "colorText": "@colorText"
                },
                "dimensions": {
                    "assetHeight": "425dp",
                    "assetWidth": "425dp",
                    "coverImageShadowRadius": "40dp",
                    "coverImageShadowVerticalOffset": "20dp",
                    "mainViewHeight": "85%",
                    "mainViewTopSpacing": "15%",
                    "primaryControlSize": "120dp",
                    "secondaryControlSize": "92dp",
                    "sliderIndeterminateHeight": "80dp",
                    "sliderPaddingTop": "@spacingMedium",
                    "trackInfoLeftPadding": "@spacingMedium",
                    "transportLayoutMargins": "0"
                },
                "numbers": {
                    "primarySongTextMaxLines": 3,
                    "secondarySongTextMaxLines": 2
                }
            },
            {
                "description": "Resource definitions for Audio template - hubLandscapeMedium",
                "when": "${@viewportProfile == @hubLandscapeMedium}",
                "dimensions": {
                    "assetHeight": "300dp",
                    "assetWidth": "300dp",
                    "primaryControlSize": "80dp",
                    "secondaryControlSize": "60dp",
                    "sliderPaddingTop": "0"
                }
            },
            {
                "description": "Resource definitions for Audio template - hubLandscapeSmall",
                "when": "${@viewportProfile == @hubLandscapeSmall}",
                "dimensions": {
                    "assetHeight": "206dp",
                    "assetWidth": "206dp",
                    "primaryControlSize": "80dp",
                    "secondaryControlSize": "60dp",
                    "sliderIndeterminateHeight": "60dp",
                    "sliderPaddingTop": "0"
                },
                "numbers": {
                    "primarySongTextMaxLines": 1,
                    "secondarySongTextMaxLines": 2
                }
            },
            {
                "description": "Resource definitions for Audio template - round",
                "when": "${@viewportProfile == @hubRoundSmall}",
                "dimensions": {
                    "assetHeight": "96dp",
                    "assetWidth": "96dp",
                    "mainViewHeight": "80%",
                    "mainViewTopSpacing": "20%",
                    "primaryControlSize": "80dp",
                    "secondaryControlSize": "60dp",
                    "sliderIndeterminateHeight": "40dp",
                    "sliderPaddingTop": "@spacingSmall",
                    "trackInfoLeftPadding": 0
                },
                "numbers": {
                    "primarySongTextMaxLines": 1,
                    "secondarySongTextMaxLines": 1
                }
            },
            {
                "description": "Resource definitions for Audio template - tv full screen",
                "when": "${@viewportProfile == @tvLandscapeXLarge}",
                "dimensions": {
                    "assetHeight": "240dp",
                    "assetWidth": "240dp",
                    "coverImageShadowRadius": "20dp",
                    "coverImageShadowVerticalOffset": "10dp",
                    "primaryControlSize": "60dp",
                    "secondaryControlSize": "46dp",
                    "sliderIndeterminateHeight": "40dp"
                },
                "numbers": {
                    "primarySongTextMaxLines": 4,
                    "secondarySongTextMaxLines": 2
                }
            },
            {
                "when": "${viewport.theme == 'light'}",
                "colors": {
                    "colorText": "@colorTextReversed"
                }
            }
        ],
        "layouts": {
            "AudioPlayer": {
                "parameters": [
                    {
                        "name": "audioControlType",
                        "description": "The type of audio control to use. Default is skip (foward and backwards). Other options are skip | jump10 | jump30 | none.",
                        "type": "string",
                        "default": "skip"
                    },
                    {
                        "name": "audioSources",
                        "description": "Audio single source or an array of sources. Audios will be in a playlist if multiple sources are provided.",
                        "type": "any"
                    },
                    {
                        "name": "backgroundImageSource",
                        "description": "URL for the background image source.",
                        "type": "string"
                    },
                    {
                        "name": "coverImageSource",
                        "description": "URL for the cover image source. If not provided, text content will be left aligned.",
                        "type": "string"
                    },
                    {
                        "name": "headerTitle",
                        "description": "Title text to render in the header.",
                        "type": "string"
                    },
                    {
                        "name": "headerSubtitle",
                        "description": "Subtitle Text to render in the header.",
                        "type": "string"
                    },
                    {
                        "name": "headerAttributionImage",
                        "description": "URL for attribution image or logo source (PNG/vector).",
                        "type": "string"
                    },
                    {
                        "name": "primaryText",
                        "description": "Primary text for the media.",
                        "type": "string"
                    },
                    {
                        "name": "secondaryText",
                        "description": "Secondary text for the media.",
                        "type": "string"
                    },
                    {
                        "name": "sliderType",
                        "description": "Determinate for full control of the slider with transport control. Indeterminate is an ambient progress bar with animation.",
                        "type": "string",
                        "default": "determinate"
                    }
                ],
                "item": [
                    {
                        "type": "Container",
                        "height": "100vh",
                        "width": "100vw",
                        "bind": [
                            {
                                "name": "sliderThumbPosition",
                                "type": "number",
                                "value": 0
                            },
                            {
                                "name": "sliderActive",
                                "type": "boolean",
                                "value": False
                            },
                            {
                                "name": "videoProgressValue",
                                "type": "number",
                                "value": 0
                            },
                            {
                                "name": "videoTotalValue",
                                "type": "number",
                                "value": 0
                            }
                        ],
                        "items": [
                            {
                                "type": "AlexaBackground",
                                "id": "AlexaBackground",
                                "description": "Main backgroud",
                                "backgroundImageSource": "${backgroundImageSource}"
                            },
                            {
                                "type": "AlexaHeader",
                                "id": "AlexaHeader",
                                "width": "100%",
                                "headerTitle": "${headerTitle}",
                                "headerSubtitle": "${headerSubtitle}",
                                "headerAttributionImage": "${headerAttributionImage}"
                            },
                            {
                                "type": "Container",
                                "position": "absolute",
                                "width": "100%",
                                "height": "@mainViewHeight",
                                "top": "@mainViewTopSpacing",
                                "alignItems": "center",
                                "justifyContent": "center",
                                "items": [
                                    {
                                        "description": "Cover image and track info",
                                        "type": "Container",
                                        "width": "100%",
                                        "paddingLeft": "@marginHorizontal",
                                        "paddingRight": "@marginHorizontal",
                                        "height": "auto",
                                        "direction": "${@viewportProfile != @hubRoundSmall ? 'row' : 'column'}",
                                        "items": [
                                            {
                                                "description": "Cover image",
                                                "type": "Container",
                                                "id": "Audio_CoverImage",
                                                "paddingEnd": "${coverImageSource != '' ? @trackInfoLeftPadding : 0}",
                                                "justifyContent": "${@viewportProfile != @hubRoundSmall ? 'center' : 'end'}",
                                                "items": [
                                                    {
                                                        "when": "${@viewportProfile != @hubRoundSmall && coverImageSource != ''}",
                                                        "type": "Container",
                                                        "height": "@assetHeight",
                                                        "width": "@assetWidth",
                                                        "items": [
                                                            {
                                                                "type": "AlexaImage",
                                                                "imageSource": "${coverImageSource}",
                                                                "imageScale": "best-fill",
                                                                "imageWidth": "@assetWidth",
                                                                "imageHeight": "@assetHeight",
                                                                "imageAspectRatio": "square",
                                                                "imageShadow": True
                                                            }
                                                        ]
                                                    }
                                                ]
                                            },
                                            {
                                                "description": "Track Info",
                                                "type": "Container",
                                                "height": "${@viewportProfile != @hubRoundSmall ? '@assetHeight' : 'auto'}",
                                                "direction": "column",
                                                "shrink": 1,
                                                "alignItems": "${@viewportProfile != @hubRoundSmall ? 'start' : 'bottom'}",
                                                "justifyContent": "end",
                                                "items": [
                                                    {
                                                        "type": "Text",
                                                        "id": "Audio_PrimaryText",
                                                        "accessibilityLabel": "${primaryText}",
                                                        "text": "${primaryText}",
                                                        "style": "textStyleDisplay4",
                                                        "textAlign": "${@viewportProfile != @hubRoundSmall ? 'auto' : 'center'}",
                                                        "paddingBottom": "@spacingXSmall"
                                                    },
                                                    {
                                                        "type": "Text",
                                                        "id": "Audio_SecondaryText",
                                                        "accessibilityLabel": "${secondaryText}",
                                                        "text": "${secondaryText}",
                                                        "style": "textStyleBody",
                                                        "textAlign": "${@viewportProfile != @hubRoundSmall ? 'auto' : 'center'}"
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        "type": "Container",
                                        "description": "Slider and controls.",
                                        "id": "Audio_AudioInfo",
                                        "width": "100%",
                                        "paddingLeft": "${@marginHorizontal - @spacingMedium}",
                                        "paddingRight": "${@marginHorizontal - @spacingMedium}",
                                        "items": [
                                            {
                                                "description": "A hidden Video component to play the audio.",
                                                "type": "Video",
                                                "id": "videoPlayer",
                                                "height": 1,
                                                "width": 1,
                                                "scale": "best-fill",
                                                "autoplay": True,
                                                "audioTrack": "background",
                                                "source": "${audioSources}",
                                                "position": "absolute",
                                                "onPlay": [
                                                    {
                                                        "type": "SetValue",
                                                        "property": "videoTotalValue",
                                                        "value": "${event.duration}"
                                                    }
                                                ],
                                                "onTrackUpdate": [
                                                    {
                                                        "type": "SetValue",
                                                        "property": "videoTotalValue",
                                                        "value": "${event.duration}"
                                                    }
                                                ],
                                                "onTimeUpdate": [
                                                    {
                                                        "type": "SetValue",
                                                        "property": "videoProgressValue",
                                                        "value": "${event.currentTime}"
                                                    },
                                                    {
                                                        "type": "SetValue",
                                                        "componentId": "slider",
                                                        "property": "progressValue",
                                                        "value": "${videoProgressValue}"
                                                    },
                                                    {
                                                        "type": "SetValue",
                                                        "property": "videoTotalValue",
                                                        "value": "${event.duration}"
                                                    }
                                                ],
                                                "onTrackReady": [
                                                    {
                                                        "type": "SetValue",
                                                        "property": "videoTotalValue",
                                                        "value": "${event.duration}"
                                                    }
                                                ],
                                                "onTrackFail": [
                                                    {
                                                        "type": "SetValue",
                                                        "property": "videoTotalValue",
                                                        "value": "0"
                                                    }
                                                ]
                                            },
                                            {
                                                "description": "Determinate Slider Container",
                                                "when": "${sliderType != 'indeterminate'}",
                                                "type": "Container",
                                                "width": "100%",
                                                "paddingTop": "@sliderPaddingTop",
                                                "items": [
                                                    {
                                                        "type": "Container",
                                                        "width": "100%",
                                                        "alignItems": "center",
                                                        "item": [
                                                            {
                                                                "type": "AlexaSlider",
                                                                "id": "slider",
                                                                "progressValue": "${videoProgressValue}",
                                                                "totalValue": "${videoTotalValue}",
                                                                "positionPropertyName": "sliderThumbPosition",
                                                                "metadataDisplayed": True,
                                                                "metadataPosition": "above_right",
                                                                "width": "100%",
                                                                "theme": "${viewport.theme}",
                                                                "onUpCommand": [
                                                                    {
                                                                        "type": "ControlMedia",
                                                                        "componentId": "videoPlayer",
                                                                        "command": "seek",
                                                                        "value": "${sliderThumbPosition - videoProgressValue}"
                                                                    }
                                                                ],
                                                                "onMoveCommand": [
                                                                    {
                                                                        "type": "SetValue",
                                                                        "property": "sliderActive",
                                                                        "value": True
                                                                    }
                                                                ],
                                                                "onDownCommand": [
                                                                    {
                                                                        "type": "SetValue",
                                                                        "property": "sliderActive",
                                                                        "value": True
                                                                    }
                                                                ]
                                                            },
                                                            {
                                                                "type": "AlexaTransportControls",
                                                                "mediaComponentId": "videoPlayer",
                                                                "playPauseToggleButtonId": "playPauseToggleButtonId",
                                                                "primaryControlSize": "@primaryControlSize",
                                                                "secondaryControls": "${audioControlType}",
                                                                "secondaryControlSize": "@secondaryControlSize",
                                                                "autoplay": True,
                                                                "theme": "${viewport.theme}"
                                                            }
                                                        ]
                                                    }
                                                ]
                                            },
                                            {
                                                "description": "Indeterminate Slider Container",
                                                "when": "${sliderType == 'indeterminate'}",
                                                "type": "Container",
                                                "width": "100%",
                                                "height": "@sliderIndeterminateHeight",
                                                "alignItems": "center",
                                                "justifyContent": "end",
                                                "item": [
                                                    {
                                                        "type": "AlexaProgressBar",
                                                        "progressBarType": "indeterminate",
                                                        "width": "${viewport.width - (@marginHorizontal*2)}"
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        },
        "mainTemplate": {
            "parameters": [
                "payload"
            ],
            "items": [
                {
                    "type": "AudioPlayer",
                    "audioControlType": "${payload.audioPlayerTemplateData.properties.audioControlType}",
                    "audioSources": "${payload.audioPlayerTemplateData.properties.audioSources}",
                    "backgroundImageSource": "${payload.audioPlayerTemplateData.properties.backgroundImage}",
                    "coverImageSource": "${payload.audioPlayerTemplateData.properties.coverImageSource}",
                    "headerAttributionImage": "${payload.audioPlayerTemplateData.properties.logoUrl}",
                    "headerTitle": "${payload.audioPlayerTemplateData.properties.headerTitle}",
                    "headerSubtitle": "",
                    "primaryText": "${payload.audioPlayerTemplateData.properties.primaryText}",
                    "secondaryText": "${payload.audioPlayerTemplateData.properties.secondaryText}",
                    "sliderType": "${payload.audioPlayerTemplateData.properties.sliderType}"
                }
            ]
        }
    }
    response_builder.add_directive(
        RenderDocumentDirective(
            token="playbackToken",
            document=apl_document,
            datasources={}
        )
    )