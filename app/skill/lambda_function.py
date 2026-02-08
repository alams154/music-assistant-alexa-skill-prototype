# -*- coding: utf-8 -*-

import logging
import gettext

import time
import base64
import json
from ask_sdk.standard import StandardSkillBuilder
from ask_sdk_core.dispatch_components import (
    AbstractRequestHandler, AbstractExceptionHandler,
    AbstractRequestInterceptor, AbstractResponseInterceptor)
from ask_sdk_core.utils import is_request_type, is_intent_name
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response

from . import data, util


from .ma_library import fetch_tracks_by_artist
sb = StandardSkillBuilder()
# sb = StandardSkillBuilder(
#     table_name=data.jingle["db_table"], auto_create_table=True)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class _ComponentFilter(logging.Filter):
    """Inject a `component` attribute based on logger name.

    This makes it easy to tell whether a message came from the
    API, the Alexa Skill code (Skill), or the UI/Web app.
    """
    def filter(self, record):
        name = (record.name or "")
        if name.startswith('music_assistant_api') or name.startswith('ma_routes'):
            record.component = 'API'
        elif name.startswith('alexa') or name == 'lambda_function' or name.startswith('ask_sdk'):
            record.component = 'Skill'
        else:
            record.component = 'UI/Web'
        return True


_filter = _ComponentFilter()
root_logger = logging.getLogger()
root_logger.addFilter(_filter)

# Ensure every LogRecord has a `component` attribute so formatters
# that reference %(component)s don't fail for third-party loggers
# (e.g. werkzeug) which may emit records before filters run.
_orig_log_record_factory = logging.getLogRecordFactory()

def _log_record_factory(*args, **kwargs):
    record = _orig_log_record_factory(*args, **kwargs)
    if not hasattr(record, 'component'):
        name = (getattr(record, 'name', '') or '')
        if name.startswith('music_assistant_api') or name.startswith('ma_routes'):
            record.component = 'API'
        elif name.startswith('alexa') or name == 'lambda_function' or name.startswith('ask_sdk'):
            record.component = 'Skill'
        else:
            record.component = 'UI/Web'
    return record

logging.setLogRecordFactory(_log_record_factory)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(component)s] %(name)s %(message)s"
)

supports_apl = False




PLAYLISTS = {}  # key -> {"tracks": [...], "idx": int, "expires": float}
PLAYLIST_TTL_SEC = 60 * 30  # 30 min

def _pl_key(handler_input: HandlerInput) -> str:
    user_id = handler_input.request_envelope.context.system.user.user_id
    device_id = handler_input.request_envelope.context.system.device.device_id
    return f"{user_id}:{device_id}"

def _cleanup_playlists() -> None:
    now = time.time()
    for k in list(PLAYLISTS.keys()):
        if PLAYLISTS[k].get("expires", 0) < now:
            del PLAYLISTS[k]

def _get_stream_url(request):
    """Return (url, audio_data) where url is resolved from util.audio_data.

    Handles multiple shapes returned by util.audio_data and never raises.
    """
    try:
        audio = util.audio_data(request)
    except Exception:
        audio = None

    url = None
    if isinstance(audio, dict):
        url = (audio.get('url') or audio.get('audioSources') or
               audio.get('audio_sources') or audio.get('stream') or '')
    elif isinstance(audio, str):
        url = audio

    if url == '':
        url = None
    return url, audio

# ######################### INTENT HANDLERS #########################
# This section contains handlers for the built-in intents and generic
# request handlers like launch, session end, skill events etc.

class CheckAudioInterfaceHandler(AbstractRequestHandler):
    """Check if device supports audio play.

    This can be used as the first handler to be checked, before invoking
    other handlers, thus making the skill respond to unsupported devices
    without doing much processing.
    """
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        if handler_input.request_envelope.context.system.device:
            # Since skill events won't have device information
            return handler_input.request_envelope.context.system.device.supported_interfaces.audio_player is None
        else:
            return False

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In CheckAudioInterfaceHandler")
        _ = handler_input.attributes_manager.request_attributes["_"]
        handler_input.response_builder.speak(
            _(data.DEVICE_NOT_SUPPORTED)).set_should_end_session(True)
        return handler_input.response_builder.response


class SkillEventHandler(AbstractRequestHandler):
    """Close session for skill events or when session ends.

    Handler to handle session end or skill events (SkillEnabled,
    SkillDisabled etc.)
    """
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (handler_input.request_envelope.request.object_type.startswith(
            "AlexaSkillEvent") or
                is_request_type("SessionEndedRequest")(handler_input))

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In SkillEventHandler")
        return handler_input.response_builder.response


class LaunchRequestOrPlayAudioHandler(AbstractRequestHandler):
    """Launch radio for skill launch or PlayAudio intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_request_type("LaunchRequest")(handler_input) or
                is_intent_name("PlayAudio")(handler_input))

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In LaunchRequestOrPlayAudioHandler")

        _ = handler_input.attributes_manager.request_attributes["_"]
        request = handler_input.request_envelope.request
        url, _audio = _get_stream_url(request)
        if not url:
            logger.warning("No streamUrl available for Launch/Play request")
            handler_input.response_builder.speak(
                "Sorry, I could not retrieve the latest music stream from the API. Please check your setup.").set_should_end_session(True)
            return handler_input.response_builder.response

        return util.play(
            url=url,
            offset=0,
            text=data.WELCOME_MSG,
            response_builder=handler_input.response_builder,
            supports_apl=supports_apl
        )


class PlayArtistIntentHandler(AbstractRequestHandler):
    """Play tracks of an artist from local Music Assistant library."""
    def can_handle(self, handler_input):
        return is_intent_name("PlayArtistIntent")(handler_input)

    def handle(self, handler_input):
        logger.info("In PlayArtistIntentHandler")
        _cleanup_playlists()

        intent = getattr(handler_input.request_envelope.request, "intent", None)
        slots = getattr(intent, "slots", {}) if intent else {}
        artist_slot = slots.get("artist")
        artist_name = (getattr(artist_slot, "value", "") or "").strip() if artist_slot else ""

        if not artist_name:
            return (
                handler_input.response_builder
                .speak("Quel artiste veux-tu écouter ?")
                .ask("Dis par exemple : joue David Guetta.")
                .set_should_end_session(False)
                .response
            )

        try:
            tracks = fetch_tracks_by_artist(artist_name, limit=50)
        except Exception as e:
            logger.exception("Failed to fetch tracks from Music Assistant: %s", e)
            return (
                handler_input.response_builder
                .speak("Désolé, je n'arrive pas à accéder à Music Assistant pour le moment.")
                .set_should_end_session(True)
                .response
            )

        if not tracks:
            return (
                handler_input.response_builder
                .speak(f"Je n'ai trouvé aucun titre de {artist_name} dans ta bibliothèque Music Assistant.")
                .set_should_end_session(True)
                .response
            )

        k = _pl_key(handler_input)
        PLAYLISTS[k] = {"tracks": tracks, "idx": 0, "expires": time.time() + PLAYLIST_TTL_SEC}
        first = tracks[0]

        return util.play(
            url=first["url"],
            offset=0,
            text=f"D'accord. Je lance {artist_name}.",
            response_builder=handler_input.response_builder,
            supports_apl=supports_apl
        )


class NextIntentHandler(AbstractRequestHandler):
    """Override NEXT to move inside the MA artist queue."""
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.NextIntent")(handler_input)

    def handle(self, handler_input):
        _cleanup_playlists()
        k = _pl_key(handler_input)
        pl = PLAYLISTS.get(k)

        if not pl or not pl.get("tracks"):
            return (
                handler_input.response_builder
                .speak("Je n'ai rien en file d'attente. Dis par exemple : joue David Guetta.")
                .set_should_end_session(True)
                .response
            )

        pl["idx"] = min(pl["idx"] + 1, len(pl["tracks"]) - 1)
        pl["expires"] = time.time() + PLAYLIST_TTL_SEC
        tr = pl["tracks"][pl["idx"]]

        return util.play(
            url=tr["url"],
            offset=0,
            text=None,
            response_builder=handler_input.response_builder,
            supports_apl=supports_apl
        )


class PreviousIntentHandler(AbstractRequestHandler):
    """Override PREVIOUS to move inside the MA artist queue."""
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.PreviousIntent")(handler_input)

    def handle(self, handler_input):
        _cleanup_playlists()
        k = _pl_key(handler_input)
        pl = PLAYLISTS.get(k)

        if not pl or not pl.get("tracks"):
            return (
                handler_input.response_builder
                .speak("Je n'ai rien en file d'attente. Dis par exemple : joue David Guetta.")
                .set_should_end_session(True)
                .response
            )

        pl["idx"] = max(pl["idx"] - 1, 0)
        pl["expires"] = time.time() + PLAYLIST_TTL_SEC
        tr = pl["tracks"][pl["idx"]]

        return util.play(
            url=tr["url"],
            offset=0,
            text=None,
            response_builder=handler_input.response_builder,
            supports_apl=supports_apl
        )

class HelpIntentHandler(AbstractRequestHandler):
    """Handler for providing help information to user."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In HelpIntentHandler")
        _ = handler_input.attributes_manager.request_attributes["_"]
        handler_input.response_builder.speak(
            _(data.HELP_MSG).format(
                util.audio_data(
                    handler_input.request_envelope.request))
        ).set_should_end_session(False)
        return handler_input.response_builder.response


class UnhandledIntentHandler(AbstractRequestHandler):
    """Handler for fallback intent, for unmatched utterances.

    2018-July-12: AMAZON.FallbackIntent is currently available in all
    English locales. This handler will not be triggered except in that
    locale, so it can be safely deployed for any locale. More info
    on the fallback intent can be found here:
    https://developer.amazon.com/docs/custom-skills/standard-built-in-intents.html#fallback
    """
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In UnhandledIntentHandler")
        _ = handler_input.attributes_manager.request_attributes["_"]
        handler_input.response_builder.speak(
            _(data.UNHANDLED_MSG)).set_should_end_session(True)
        return handler_input.response_builder.response


class NextOrPreviousIntentHandler(AbstractRequestHandler):
    """Handler for next or previous intents."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("AMAZON.NextIntent")(handler_input) or
                is_intent_name("AMAZON.PreviousIntent")(handler_input))

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In NextOrPreviousIntentHandler")
        _ = handler_input.attributes_manager.request_attributes["_"]
        handler_input.response_builder.speak(
            _(data.CANNOT_SKIP_MSG)).set_should_end_session(True)
        return handler_input.response_builder.response


class CancelOrStopIntentHandler(AbstractRequestHandler):
    """Handler for cancel and stop intents."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("AMAZON.CancelIntent")(handler_input) or
                is_intent_name("AMAZON.StopIntent")(handler_input))

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In CancelOrStopIntentHandler")
        _ = handler_input.attributes_manager.request_attributes["_"]
        return util.stop(_(data.STOP_MSG), handler_input.response_builder, supports_apl=supports_apl)


class PauseIntentHandler(AbstractRequestHandler):
    """Handler for AMAZON.PauseIntent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("AMAZON.PauseIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In PauseIntentHandler")
        _ = handler_input.attributes_manager.request_attributes["_"]
        return util.stop(text=None,
                         response_builder=handler_input.response_builder,
                         supports_apl=supports_apl)


class ResumeIntentHandler(AbstractRequestHandler):
    """Handler for resume intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_intent_name("AMAZON.ResumeIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In ResumeIntentHandler")
        request = handler_input.request_envelope.request
        _ = handler_input.attributes_manager.request_attributes["_"]
        url, _audio = _get_stream_url(request)
        if not url:
            logger.warning("No stream url available for Resume request")
            handler_input.response_builder.speak(
                "Sorry, I couldn't reach the stream right now.").set_should_end_session(True)
            return handler_input.response_builder.response

        return util.play(
            url=url, 
            offset=0,
            text=data.WELCOME_MSG,
            response_builder=handler_input.response_builder,
            supports_apl=supports_apl
        )


class StartOverIntentHandler(AbstractRequestHandler):
    """Handler for start over, loop on/off, shuffle on/off intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("AMAZON.StartOverIntent")(handler_input) or
                is_intent_name("AMAZON.LoopOnIntent")(handler_input) or
                is_intent_name("AMAZON.LoopOffIntent")(handler_input) or
                is_intent_name("AMAZON.ShuffleOnIntent")(handler_input) or
                is_intent_name("AMAZON.ShuffleOffIntent")(handler_input))

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In StartOverIntentHandler")

        _ = handler_input.attributes_manager.request_attributes["_"]
        speech = _(data.NOT_POSSIBLE_MSG)
        return handler_input.response_builder.speak(speech).response

# ###################################################################

# ########## AUDIOPLAYER INTERFACE HANDLERS #########################
# This section contains handlers related to Audioplayer interface

class PlaybackStartedHandler(AbstractRequestHandler):
    """AudioPlayer.PlaybackStarted Directive received.

    Confirming that the requested audio file began playing.
    Do not send any specific response.
    """
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_request_type("AudioPlayer.PlaybackStarted")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In PlaybackStartedHandler")
        logger.info("Playback started")
        return handler_input.response_builder.response

class PlaybackFinishedHandler(AbstractRequestHandler):
    """AudioPlayer.PlaybackFinished Directive received.

    Confirming that the requested audio file completed playing.
    Do not send any specific response.
    """
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_request_type("AudioPlayer.PlaybackFinished")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In PlaybackFinishedHandler")
        logger.info("Playback finished")
        return handler_input.response_builder.response


class PlaybackStoppedHandler(AbstractRequestHandler):
    """AudioPlayer.PlaybackStopped Directive received.

    Confirming that the requested audio file stopped playing.
    Do not send any specific response.
    """
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_request_type("AudioPlayer.PlaybackStopped")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In PlaybackStoppedHandler")
        logger.info("Playback stopped")
        return handler_input.response_builder.response


class PlaybackNearlyFinishedHandler(AbstractRequestHandler):
    """AudioPlayer.PlaybackNearlyFinished Directive received.

    Replacing queue with the URL again. This should not happen on live streams.
    """
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_request_type("AudioPlayer.PlaybackNearlyFinished")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In PlaybackNearlyFinishedHandler")
        logger.info("Playback nearly finished")
        request = handler_input.request_envelope.request
        url, _audio = _get_stream_url(request)
        if not url:
            logger.warning("No stream url available for PlaybackNearlyFinished")
            return handler_input.response_builder.response

        return util.play_later(
            url=url,
            response_builder=handler_input.response_builder
        )


class PlaybackFailedHandler(AbstractRequestHandler):
    """AudioPlayer.PlaybackFailed Directive received.

    Logging the error and restarting playing with no output speech and card.
    """
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_request_type("AudioPlayer.PlaybackFailed")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In PlaybackFailedHandler")
        request = handler_input.request_envelope.request
        logger.info("Playback failed: {}".format(request.error))
        url, _audio = _get_stream_url(request)
        if not url:
            logger.warning("No stream url available for PlaybackFailed; skipping restart")
            return handler_input.response_builder.response

        return util.play(
            url=url, 
            offset=0, 
            text=None,
            response_builder=handler_input.response_builder,
            supports_apl=supports_apl
        )


class ExceptionEncounteredHandler(AbstractRequestHandler):
    """Handler to handle exceptions from responses sent by AudioPlayer
    request.
    """
    def can_handle(self, handler_input):
        # type; (HandlerInput) -> bool
        return is_request_type("System.ExceptionEncountered")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("\n**************** EXCEPTION *******************")
        logger.info(handler_input.request_envelope)
        return handler_input.response_builder.response

# ###################################################################

# ########## PLAYBACK CONTROLLER INTERFACE HANDLERS #################
# This section contains handlers related to Playback Controller interface
# https://developer.amazon.com/docs/custom-skills/playback-controller-interface-reference.html#requests

class PlayCommandHandler(AbstractRequestHandler):
    """Handler for Play command from hardware buttons or touch control.

    This handler handles the play command sent through hardware buttons such
    as remote control or the play control from Alexa-devices with a screen.
    """
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_request_type(
            "PlaybackController.PlayCommandIssued")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In PlayCommandHandler")
        _ = handler_input.attributes_manager.request_attributes["_"]
        request = handler_input.request_envelope.request
        url, _audio = _get_stream_url(request)
        if not url:
            logger.warning("No stream url available for PlayCommand; notifying user")
            handler_input.response_builder.speak(
                "Sorry, I couldn't reach the stream right now.").set_should_end_session(True)
            return handler_input.response_builder.response

        return util.play(
            url=url,
            offset=0,
            text=None,
            response_builder=handler_input.response_builder,
            supports_apl=supports_apl
        )


class NextOrPreviousCommandHandler(AbstractRequestHandler):
    """Handler for Next or Previous command from hardware buttons or touch
    control.

    This handler handles the next/previous command sent through hardware
    buttons such as remote control or the next/previous control from
    Alexa-devices with a screen.
    """
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_request_type(
            "PlaybackController.NextCommandIssued")(handler_input) or
                is_request_type(
                    "PlaybackController.PreviousCommandIssued")(handler_input))

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In NextOrPreviousCommandHandler")
        return handler_input.response_builder.response


class PauseCommandHandler(AbstractRequestHandler):
    """Handler for Pause command from hardware buttons or touch control.

    This handler handles the pause command sent through hardware
    buttons such as remote control or the pause control from
    Alexa-devices with a screen.
    """
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return is_request_type("PlaybackController.PauseCommandIssued")(
            handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In PauseCommandHandler")
        return util.stop(text=None,
                         response_builder=handler_input.response_builder,
                         supports_apl=supports_apl)

# ###################################################################

# ################## EXCEPTION HANDLERS #############################
class CatchAllExceptionHandler(AbstractExceptionHandler):
    """Catch all exception handler, log exception and
    respond with custom message.
    """
    def can_handle(self, handler_input, exception):
        # type: (HandlerInput, Exception) -> bool
        return True

    def handle(self, handler_input, exception):
        # type: (HandlerInput, Exception) -> Response
        logger.info("In CatchAllExceptionHandler")
        logger.error(exception, exc_info=True)
        _ = handler_input.attributes_manager.request_attributes["_"]
        handler_input.response_builder.speak(_(data.UNHANDLED_MSG)).ask(
            _(data.HELP_MSG).format(
                util.audio_data(handler_input.request_envelope.request)))

        return handler_input.response_builder.response

# ###################################################################

# ############# REQUEST / RESPONSE INTERCEPTORS #####################

class APLSupportRequestInterceptor(AbstractRequestInterceptor):
    """Request Interceptor to check if the device supports APL and update the global supports_apl variable."""
    def process(self, handler_input):
        global supports_apl
        if hasattr(handler_input, 'request_envelope'):
            supported_interfaces = getattr(
                handler_input.request_envelope.context.system.device.supported_interfaces,
                'alexa_presentation_apl', None)
            supports_apl = supported_interfaces is not None
        else:
            supports_apl = False

class RequestLogger(AbstractRequestInterceptor):
    """Log the alexa requests."""
    def process(self, handler_input):
        # type: (HandlerInput) -> None
        request = handler_input.request_envelope.request
        try:
            req_type = getattr(request, 'object_type', type(request).__name__)
            # If this is an IntentRequest, log intent name and slots
            if hasattr(request, 'intent') and request.intent:
                intent_name = getattr(request.intent, 'name', None)
                slots = {}
                intent_slots = getattr(request.intent, 'slots', None)
                if intent_slots:
                    for slot_key, slot_obj in intent_slots.items():
                        slots[slot_key] = getattr(slot_obj, 'value', None)

                logger.info("Incoming Intent: %s - Slots: %s", intent_name, slots)
            else:
                logger.info("Incoming Request Type: %s", req_type)
        except Exception:
            logger.exception("Failed to log incoming request details")

        # Keep a debug-level dump of the full request for deep troubleshooting
        logger.debug("Alexa Request: %s", request)


class LocalizationInterceptor(AbstractRequestInterceptor):
    """Process the locale in request and load localized strings for response.

    This interceptors processes the locale in request, and loads the locale
    specific localization strings for the function `_`, that is used during
    responses.
    """
    def process(self, handler_input):
        # type: (HandlerInput) -> None
        locale = getattr(handler_input.request_envelope.request, 'locale', None)
        logger.info("Locale is {}".format(locale))
        if locale:
            if locale.startswith("fr"):
                locale_file_name = "fr-FR"
            elif locale.startswith("it"):
                locale_file_name = "it-IT"
            elif locale.startswith("es"):
                locale_file_name = "es-ES"
            elif locale.startswith("pt"):
                locale_file_name = "pt-BR"
            elif locale.startswith("de"):
                locale_file_name = "de-DE"
            else:
                locale_file_name = locale

            logger.info("Loading locale file: {}".format(locale_file_name))
            i18n = gettext.translation(
                'data', localedir='locales', languages=[locale_file_name],
                fallback=True)
            handler_input.attributes_manager.request_attributes[
                "_"] = i18n.gettext
        else:
            handler_input.attributes_manager.request_attributes[
                "_"] = gettext.gettext


class ResponseLogger(AbstractResponseInterceptor):
    """Log the alexa responses."""
    def process(self, handler_input, response):
        # type: (HandlerInput, Response) -> None
        logger.debug("Alexa Response: {}".format(response))

# ###################################################################


# ############# REGISTER HANDLERS #####################
# Request Handlers
sb.add_request_handler(CheckAudioInterfaceHandler())
sb.add_request_handler(SkillEventHandler())
sb.add_request_handler(LaunchRequestOrPlayAudioHandler())
sb.add_request_handler(PlayCommandHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(ExceptionEncounteredHandler())
sb.add_request_handler(UnhandledIntentHandler())
sb.add_request_handler(PlayArtistIntentHandler())
sb.add_request_handler(NextIntentHandler())
sb.add_request_handler(PreviousIntentHandler())
sb.add_request_handler(NextOrPreviousIntentHandler())
sb.add_request_handler(NextOrPreviousCommandHandler())
sb.add_request_handler(PauseIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_request_handler(PauseCommandHandler())
sb.add_request_handler(ResumeIntentHandler())
sb.add_request_handler(StartOverIntentHandler())
sb.add_request_handler(PlaybackStartedHandler())
sb.add_request_handler(PlaybackFinishedHandler())
sb.add_request_handler(PlaybackStoppedHandler())
sb.add_request_handler(PlaybackNearlyFinishedHandler())
sb.add_request_handler(PlaybackFailedHandler())

# Exception handlers
sb.add_exception_handler(CatchAllExceptionHandler())

# Interceptors
sb.add_global_request_interceptor(APLSupportRequestInterceptor())
sb.add_global_request_interceptor(RequestLogger())
sb.add_global_request_interceptor(LocalizationInterceptor())
sb.add_global_response_interceptor(ResponseLogger())

# AWS Lambda handler
lambda_handler = sb.lambda_handler()
