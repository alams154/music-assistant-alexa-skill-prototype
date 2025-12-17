# -*- coding: utf-8 -*-

import logging
import gettext
from ask_sdk.standard import StandardSkillBuilder
from ask_sdk_core.dispatch_components import (
    AbstractRequestHandler, AbstractExceptionHandler,
    AbstractRequestInterceptor, AbstractResponseInterceptor)
from ask_sdk_core.utils import is_request_type, is_intent_name
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response

from alexa import data, util

sb = StandardSkillBuilder()
# sb = StandardSkillBuilder(
#     table_name=data.jingle["db_table"], auto_create_table=True)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
)

supports_apl = False


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

        return util.play(url=url,
                         offset=0,
                         text=data.WELCOME_MSG,
                         response_builder=handler_input.response_builder,
                         supports_apl=supports_apl)


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
    """Handler for cancel, stop or pause intents."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_intent_name("AMAZON.CancelIntent")(handler_input) or
                is_intent_name("AMAZON.StopIntent")(handler_input) or
                is_intent_name("AMAZON.PauseIntent")(handler_input))

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In CancelOrStopIntentHandler")
        _ = handler_input.attributes_manager.request_attributes["_"]
        return util.stop(_(data.STOP_MSG), handler_input.response_builder, supports_apl=supports_apl)


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
        speech = _(data.RESUME_MSG).format(
            util.audio_data(request))
        url, _audio = _get_stream_url(request)
        if not url:
            logger.warning("No stream url available for Resume request")
            handler_input.response_builder.speak(
                "Sorry, I couldn't reach the stream right now.").set_should_end_session(True)
            return handler_input.response_builder.response

        return util.play(
            url=url, offset=0,
            text=speech,
            response_builder=handler_input.response_builder,
            supports_apl=supports_apl)


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
            response_builder=handler_input.response_builder)


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
            url=url, offset=0, text=None,
            response_builder=handler_input.response_builder,
            supports_apl=supports_apl)


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

        return util.play(url=url,
                         offset=0,
                         text=None,
                         response_builder=handler_input.response_builder,
                         supports_apl=supports_apl)


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
sb.add_request_handler(NextOrPreviousIntentHandler())
sb.add_request_handler(NextOrPreviousCommandHandler())
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
