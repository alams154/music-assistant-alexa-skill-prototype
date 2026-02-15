# -*- coding: utf-8 -*-

import datetime
import os
import re
import logging
import requests
from env_secrets import get_env_secret
from typing import Dict, Optional
from ask_sdk_model import Request, Response
from ask_sdk_model.ui import StandardCard, Image
from ask_sdk_model.interfaces.audioplayer import (
    PlayDirective, PlayBehavior, AudioItem, Stream, AudioItemMetadata,
    StopDirective, ClearQueueDirective, ClearBehavior)
from ask_sdk_model.interfaces import display
from ask_sdk_core.response_helper import ResponseFactory
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model.interfaces.alexa.presentation.apl import RenderDocumentDirective, ExecuteCommandsDirective, ControlMediaCommand, MediaCommandType
from . import data


def get_ma_hostname(raise_on_http_scheme=True):
    """Read and sanitize MA_HOSTNAME environment variable and return a https:// hostname or empty string.

    If `raise_on_http_scheme` is True and the provided value starts with http://, a
    ValueError is raised so callers can surface an appropriate error to the user.
    """
    hostname_raw = os.environ.get('MA_HOSTNAME', '')
    hostname_raw = hostname_raw.strip()
    # strip surrounding single/double quotes
    if len(hostname_raw) >= 2 and ((hostname_raw[0] == hostname_raw[-1] == '"') or (hostname_raw[0] == hostname_raw[-1] == "'")):
        hostname_raw = hostname_raw[1:-1].strip()
    # final cleanup of stray quotes/whitespace
    hostname_raw = hostname_raw.strip('"\' ')

    if hostname_raw == '':
        return ''

    hostname_clean = hostname_raw.rstrip('/')
    if hostname_clean.startswith('https://'):
        return hostname_clean
    if hostname_clean.startswith('http://'):
        if raise_on_http_scheme:
            raise ValueError('http_scheme')
        return ''

    return f'https://{hostname_clean}'


def replace_ip_in_url(url, hostname):
    """Replace an IP address host at the start of `url` with `hostname` and
    percent-encode spaces. Returns the modified url.
    """
    if not url:
        return url
    try:
        new_url = re.sub(r'^https?://\d+\.\d+\.\d+\.\d+(?::\d+)?', hostname, url)
    except re.error:
        # In case the regex fails for some odd reason, just return original
        return url.replace(' ', '%20')
    return new_url.replace(' ', '%20')

def audio_data(request):
    # type: (Request) -> Dict
    try:
        data.get_latest()
        return data.info
    except Exception:
        return


def push_alexa_metadata(url):
    """Push the currently playing stream metadata to the Alexa API"""
    payload = {
        'streamUrl': url,
        'title': data.info.get("primaryText"),
        'secondary': data.info.get("secondaryText"),
        'imageUrl': data.info.get("coverImageSource")
    }

    try:
        # Alexa API is part of the same app/container; update its module-level
        # store directly to avoid HTTP and latency.
        from app.alexa_api import alexa_routes
        alexa_routes._store = payload
    except Exception:
        # Fallback to localhost HTTP POST if direct import fails for any reason.
        try:
            push_endpoint = 'http://localhost:5000/alexa/push-url'
            user = get_env_secret('APP_USERNAME')
            pwd = get_env_secret('APP_PASSWORD')
            if user and pwd:
                requests.post(push_endpoint, json=payload, timeout=2, auth=(user, pwd))
            else:
                requests.post(push_endpoint, json=payload, timeout=2)
        except requests.RequestException:
            logging.exception('Failed to POST to Alexa API %s', push_endpoint)
        except Exception:
            logging.exception('Unexpected error while pushing Alexa metadata')


def play(url, offset, text, response_builder, supports_apl=False):
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

    if supports_apl:
        add_apl(response_builder)
    else:
        # Sanitize MA_HOSTNAME and replace IP-host in the provided stream URL.
        try:
            hostname = get_ma_hostname(raise_on_http_scheme=True)
        except ValueError:
            response_builder.speak(
                "The domain uses an unsupported scheme (http). Please check your environment variable MA_HOSTNAME.").set_should_end_session(True)
            return response_builder.response

        if not hostname:
            response_builder.speak(
                "You did not specify a valid hostname. Please check your environment variable MA_HOSTNAME.").set_should_end_session(True)
            return response_builder.response

        url = replace_ip_in_url(url, hostname)

        # Ensure the resource exists and appears playable. Try HEAD first, fall back to GET.
        try:
            head_resp = requests.head(url, allow_redirects=True, timeout=5)
            resp = head_resp
            if head_resp.status_code >= 400:
                resp = requests.get(url, stream=True, allow_redirects=True, timeout=5)

            if resp.status_code >= 400:
                logging.error('Audio URL returned HTTP %s: %s', resp.status_code, url)
                response_builder.speak(
                    "Sorry, I can't play the requested audio because the file is not available.")
                response_builder.set_should_end_session(True)
                return response_builder.response
        except requests.RequestException:
            logging.exception('Play Function URL: %s', url)
            response_builder.speak(
                "Sorry, I can't reach the audio file. Please check that your stream URL is internet accessible via HTTPS at the MA_HOSTNAME variable you provided.")
            response_builder.set_should_end_session(True)
            return response_builder.response

        response_builder.add_directive(
            PlayDirective(
                play_behavior=PlayBehavior.REPLACE_ALL,
                audio_item=AudioItem(
                    stream=Stream(
                        token=url,
                        url=url,
                        offset_in_milliseconds=offset,
                        expected_previous_token=None
                    )
                )
            )
        ).set_should_end_session(True)

    if text:
        response_builder.speak(text)

    try:
        push_alexa_metadata(url)
    except Exception:
        logging.exception('Error while preparing Alexa API push payload')

    return response_builder.response


def stop(text, response_builder, supports_apl=False):
    """Issue stop directive to stop the audio.

    Issuing AudioPlayer.Stop directive to stop the audio.
    Attributes already stored when AudioPlayer.Stopped request received.
    """
    # type: (str, ResponseFactory) -> Response
    response_builder.add_directive(StopDirective())

    if text:
        response_builder.speak(text)

    return response_builder.response


def pause(text, response_builder, supports_apl=False, session_new=False):
    """Pause playback.

    If the device supports APL, send an ExecuteCommands directive with a
    ControlMedia command for pause (token must match the rendered APL token).
    Otherwise, fall back to the AudioPlayer Stop directive.
    """
    # type: (str, ResponseFactory, bool) -> Response
    if supports_apl:
        try:
            # If this request starts a new session (Alexa sent session.new==true)
            # we need to re-render the APL document created by `play` so the
            # UI is in sync. Otherwise send an ExecuteCommands directive to
            # control the media element (pause).
            if session_new:
                try:
                    add_apl(response_builder, start_paused=True)
                except Exception:
                    logging.exception('Failed to re-render APL on session new')
                # keep the session open for further directives
                response_builder.set_should_end_session(False)
            else:
                cmd = ControlMediaCommand(command=MediaCommandType.pause, component_id="videoPlayer")
                response_builder.add_directive(
                    ExecuteCommandsDirective(
                        commands=[cmd],
                        token="playbackToken"
                    )
                ).set_should_end_session(False)
        except Exception:
            logging.exception('Failed to add APL pause command; falling back to Stop')
            response_builder.add_directive(StopDirective())
    else:
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

def add_apl(response_builder, start_paused=False):
    """Add the RenderDocumentDirective"""
    # Replace MA-hosted image sources if MA_HOSTNAME is set.
    try:
        hostname = get_ma_hostname(raise_on_http_scheme=False)
    except ValueError:
        hostname = ''

    if hostname:
        data.info["coverImageSource"] = replace_ip_in_url(data.info.get("coverImageSource", ""), hostname)

    apl_document = {
        "type": "APL",
        "version": "2024.3",
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
                                                "autoplay": (not start_paused),
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
                                                                "autoplay": (not start_paused),
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
                    "audioSources": data.info["audioSources"],
                    "backgroundImageSource": data.info["backgroundImageSource"],
                    "coverImageSource": data.info["coverImageSource"],
                    "headerAttributionImage": data.info["headerAttributionImage"],
                    "headerTitle": data.info["headerTitle"],
                    "headerSubtitle": data.info["headerSubtitle"],
                    "primaryText": data.info["primaryText"],
                    "secondaryText": data.info["secondaryText"],
                    "sliderType": "determinate"
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
