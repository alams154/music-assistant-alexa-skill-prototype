from pathlib import Path
import re

p = Path("app/skill/lambda_function.py")
txt = p.read_text(encoding="utf-8", errors="replace")

# Normalize newlines to avoid weird patch/corrupt issues
txt = txt.replace("\r\n", "\n").replace("\r", "\n")

def ensure_import(block: str, after_pattern: str, insert: str) -> str:
    if insert.strip() in block:
        return block
    m = re.search(after_pattern, block)
    if not m:
        raise SystemExit(f"Could not find pattern for import insertion: {after_pattern}")
    i = m.end()
    return block[:i] + "\n" + insert + block[i:]

# 1) Add stdlib imports after gettext import (or anywhere in top imports)
if "import time" not in txt:
    # insert after "import gettext"
    txt = ensure_import(txt, r"import gettext\s*\n", "import time\nimport base64\nimport json\n")

# 2) Add MA import after ". import data, util"
if "from .ma_library import fetch_tracks_by_artist" not in txt:
    txt = ensure_import(txt, r"from \. import data, util\s*\n", "from .ma_library import fetch_tracks_by_artist\n")

# 3) Add playlist globals/helpers after supports_apl = False
helpers = r'''
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
'''.strip("\n")

if "PLAYLIST_TTL_SEC" not in txt:
    m = re.search(r"supports_apl\s*=\s*False\s*\n", txt)
    if not m:
        raise SystemExit("Could not find 'supports_apl = False' line.")
    insert_at = m.end()
    txt = txt[:insert_at] + "\n\n" + helpers + "\n\n" + txt[insert_at:]

# 4) Add new handlers after LaunchRequestOrPlayAudioHandler class definition
handlers = r'''
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
'''.strip("\n")

if "class PlayArtistIntentHandler" not in txt:
    # Find end of LaunchRequestOrPlayAudioHandler class by locating the next "class HelpIntentHandler"
    m = re.search(r"class LaunchRequestOrPlayAudioHandler.*?\nclass HelpIntentHandler", txt, flags=re.S)
    if not m:
        raise SystemExit("Could not find insertion point after LaunchRequestOrPlayAudioHandler.")
    # Insert right before HelpIntentHandler
    insert_at = m.end() - len("class HelpIntentHandler")
    txt = txt[:insert_at] + handlers + "\n\n" + txt[insert_at:]

# Write back normalized with trailing newline
p.write_text(txt + ("\n" if not txt.endswith("\n") else ""), encoding="utf-8")
print("OK: lambda_function.py updated")
