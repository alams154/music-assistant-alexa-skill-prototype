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
from ask_sdk_model.interfaces.alexa.presentation.apl import ExecuteCommandsDirective, ControlMediaCommand, MediaCommandType
from . import data
from .apl import add_apl


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
                    "Sorry, I can't reach the audio file. Please check that your stream URL is internet accessible via HTTPS at the MA_HOSTNAME variable you provided.")
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


def update_apl_metadata(response_builder):
    """Update the APL document with the latest metadata without interrupting playback.
    
    This function sends ExecuteCommands directives to update only the text and image
    components, avoiding a full document re-render that would restart audio playback.
    This is called in response to UserEvent requests from the APL document.
    """
    # type: (ResponseFactory) -> None
    try:
        from ask_sdk_model.interfaces.alexa.presentation.apl import ExecuteCommandsDirective
        
        # Replace MA-hosted image sources if MA_HOSTNAME is set
        try:
            hostname = get_ma_hostname(raise_on_http_scheme=False)
        except ValueError:
            hostname = ''

        cover_image = data.info.get("coverImageSource", "")
        background_image = data.info.get("backgroundImageSource", "")
        
        if hostname:
            cover_image = replace_ip_in_url(cover_image, hostname)
            background_image = replace_ip_in_url(background_image, hostname)
        
        # Build SetValue commands to update individual components
        commands = []
        
        # Update primary text (song title)
        if data.info.get("primaryText"):
            commands.append({
                "type": "SetValue",
                "componentId": "Audio_PrimaryText",
                "property": "text",
                "value": data.info["primaryText"]
            })
        
        # Update secondary text (artist/album)
        if data.info.get("secondaryText"):
            commands.append({
                "type": "SetValue",
                "componentId": "Audio_SecondaryText",
                "property": "text",
                "value": data.info["secondaryText"]
            })
        
        # Update cover image and bound data so conditional rendering refreshes.
        if cover_image:
            commands.append({
                "type": "SetValue",
                "componentId": "AudioPlayerRoot",
                "property": "coverImageSource",
                "value": cover_image
            })
            commands.append({
                "type": "SetValue",
                "componentId": "Audio_CoverArt",
                "property": "imageSource",
                "value": cover_image
            })
        
        # Update background image and bound data so layouts recompute.
        if background_image:
            commands.append({
                "type": "SetValue",
                "componentId": "AudioPlayerRoot",
                "property": "backgroundImageSource",
                "value": background_image
            })
            commands.append({
                "type": "SetValue",
                "componentId": "AlexaBackground",
                "property": "backgroundImageSource",
                "value": background_image
            })
        
        # Send ExecuteCommands directive if we have any commands
        if commands:
            response_builder.add_directive(
                ExecuteCommandsDirective(
                    commands=commands,
                    token="playbackToken"
                )
            )
        else:
            logging.warning("No SetValue commands generated - no metadata to update")
        
    except Exception:
        logging.exception('Error while updating APL metadata')


def schedule_apl_refresh(response_builder, delay_ms=1000):
    """Schedule the next APL metadata refresh via a UserEvent.

    This keeps refreshes alive even if the onMount loop does not repeat.
    """
    # type: (ResponseFactory, int) -> None
    try:
        from ask_sdk_model.interfaces.alexa.presentation.apl import ExecuteCommandsDirective

        commands = [
            {
                "type": "Idle",
                "delay": int(delay_ms)
            },
            {
                "type": "SendEvent",
                "arguments": [
                    "MetadataRefresh",
                    "${refreshTick}"
                ]
            }
        ]

        response_builder.add_directive(
            ExecuteCommandsDirective(
                commands=commands,
                token="playbackToken"
            )
        )
    except Exception:
        logging.exception('Error while scheduling APL refresh')

