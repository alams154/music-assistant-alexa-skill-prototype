"""Echo Show screen driven by Music Assistant 2.11: live page contract, voice
commands, per-track time and lyrics.

Run from app/:  python -m pytest -q tests
"""
import json
import os
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("ask_sdk_core")

os.environ.setdefault("ENABLE_APL", "true")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("MA_HOSTNAME", "ma.example.org")
os.environ.setdefault("MA_API_URL", "http://ma.invalid:8095")
os.environ.setdefault("SKIP_URL_VALIDATION", "true")
os.environ.setdefault("DEVICE_MAPPING_PATH", os.path.join(tempfile.mkdtemp(), "devices.json"))

from ask_sdk_model import RequestEnvelope  # noqa: E402

import alexa_api  # noqa: E402
import music_assistant_api  # noqa: E402
import shared_store  # noqa: E402
from skill import lambda_function as lf  # noqa: E402
from skill import ma_control, util  # noqa: E402

PLAYER = "pl0123456789ab"
DOC = json.loads((Path(lf.__file__).parent / "apl_document.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """Map the test Echo to PLAYER, record MA commands, never touch the network."""
    calls = []
    monkeypatch.setattr(lf.device_mapping, "get_player_for_device", lambda d: PLAYER if d == "d" else None)
    monkeypatch.setattr(ma_control, "send_player_command",
                        lambda p, c, ref_item_id=None: calls.append((p, c, ref_item_id)) or True)
    monkeypatch.setattr(ma_control, "get_now_playing", lambda p: None)
    monkeypatch.setattr(ma_control, "get_queue_state", lambda p: "playing")
    monkeypatch.setattr(ma_control, "get_lyrics", lambda p: None)
    monkeypatch.setattr(util, "push_alexa_metadata", lambda url: None)
    shared_store._live_pages.clear()
    shared_store._pending.clear()
    shared_store._rendered_stream.clear()
    lf._now_playing_state.clear()
    return calls


def _envelope(request, apl=True):
    interfaces = {"AudioPlayer": {}}
    if apl:
        interfaces["Alexa.Presentation.APL"] = {"runtime": {"maxVersion": "2023.3"}}
    return {
        "version": "1.0",
        "session": {"new": False, "sessionId": "s", "application": {"applicationId": ""},
                    "user": {"userId": "u"}},
        "context": {"System": {"application": {"applicationId": ""}, "user": {"userId": "u"},
                               "device": {"deviceId": "d", "supportedInterfaces": interfaces},
                               "apiEndpoint": "https://api.eu.amazonalexa.com"}},
        "request": {"requestId": "r", "locale": "fr-FR", "timestamp": "2026-11-27T12:00:00Z", **request},
    }


def _invoke(request):
    skill = lf.sb.create()
    envelope = skill.serializer.deserialize(json.dumps(_envelope(request)), RequestEnvelope)
    return skill.serializer.serialize(skill.invoke(request_envelope=envelope, context=None))["response"]


def _intent(name):
    return _invoke({"type": "IntentRequest", "intent": {"name": name, "confirmationStatus": "NONE"}})


# ----------------------------------------------------------------- live page contract (MA 2.11)
def test_push_url_answers_page_live_and_queues_the_stream():
    ma = music_assistant_api.create_ma_app().test_client()
    body = {"streamUrl": "http://ma:8097/flow/s1/x/i1/Echo.flac", "title": "T", "artist": "A",
            "album": "B", "imageUrl": "", "playerId": PLAYER, "canSkipSpeech": True}
    assert ma.post("/push-url", json=body).get_json()["pageLive"] is False   # no screen: MA speaks
    shared_store.mark_page_live(PLAYER)
    assert ma.post("/push-url", json=body).get_json()["pageLive"] is True
    assert shared_store.pop_pending(PLAYER) == ["stream"]


def test_control_pause_resume_and_unknown_command():
    ma = music_assistant_api.create_ma_app().test_client()
    shared_store.mark_page_live(PLAYER)
    for command in ("pause", "resume"):
        r = ma.post("/control", json={"playerId": PLAYER, "command": command, "canSkipSpeech": True})
        assert r.get_json() == {"pageLive": True}
    assert ma.post("/control", json={"playerId": PLAYER, "command": "jump"}).status_code == 400


def test_playback_state_reports_the_screen_position():
    shared_store.mark_page_live(PLAYER)
    shared_store.set_report(PLAYER, "PLAYING", 12345, "http://ma:8097/flow/s1/x/i1/Echo.mp3")
    shared_store._store = {"streamUrl": "http://ma:8097/flow/s1/x/i1/Echo.flac"}
    state = alexa_api.create_alexa_app().test_client().get(f"/playback-state?player_id={PLAYER}").get_json()
    assert state["activity"] == "PLAYING" and state["offsetMs"] == 12345
    assert state["current"] is True                    # same stream, other host/extension
    assert {"ageSeconds", "observedAt"} <= set(state)
    shared_store._live_pages.clear()                   # screen closed: not playing any more
    state = alexa_api.create_alexa_app().test_client().get(f"/playback-state?player_id={PLAYER}").get_json()
    assert state["activity"] != "PLAYING"


# ----------------------------------------------------------------- voice
def test_voice_next_keeps_the_live_screen_open(_isolated):
    shared_store.mark_page_live(PLAYER)
    response = _intent("AMAZON.NextIntent")
    assert [c[1] for c in _isolated] == ["next"]
    assert "shouldEndSession" not in response


def test_french_extra_phrasings_map_to_previous(_isolated):
    _intent("MaPreviousIntent")
    assert [c[1] for c in _isolated] == ["previous"]


def test_play_audio_on_a_live_screen_only_resumes():
    shared_store.mark_page_live(PLAYER)
    response = _intent("PlayAudio")
    kinds = [d["type"].split(".")[-1] for d in response.get("directives", [])]
    assert kinds == ["ExecuteCommands"] and "shouldEndSession" not in response


def test_unrecognized_utterance_does_not_close_a_live_screen():
    shared_store.mark_page_live(PLAYER)
    response = _intent("AMAZON.FallbackIntent")
    assert "shouldEndSession" not in response and "outputSpeech" not in response


def test_every_standard_model_has_next_and_previous():
    for path in (Path(lf.__file__).parent.parent / "models").glob("*.json"):
        intents = json.loads(path.read_text(encoding="utf-8"))["interactionModel"]["languageModel"]["intents"]
        names = {i.get("name") for i in intents}
        if None in names:
            continue                                     # other (non-deployable) format
        assert {"AMAZON.NextIntent", "AMAZON.PreviousIntent"} <= names, path.name


# ----------------------------------------------------------------- per-track time
def test_offset_follows_the_previous_track_exactly():
    lf._screen_pos[PLAYER] = {"current": 181000, "offset": 1000, "playing": True, "t": lf._time.time()}
    state = {}
    cmds = lf._flow_time_commands(PLAYER, state, {"queue_item_id": "b", "duration_ms": 200000},
                                  "a", 180000)
    offset = [c for c in cmds if c["property"] == "trackOffset"][0]
    assert offset["value"] == 181000 and offset["componentId"] == "videoPlayer"
    assert state["exact"] is True


def test_stream_ran_dry_at_the_end_of_the_track():
    lf._now_playing_state[PLAYER] = {"last_duration": 200000}
    assert lf._ran_out_at_track_end(PLAYER, {"current": 198500, "offset": 0})
    assert not lf._ran_out_at_track_end(PLAYER, {"current": 60000, "offset": 0})


# ----------------------------------------------------------------- lyrics
def test_lrc_lyrics_parsed_with_lead_and_lookup_table(monkeypatch):
    monkeypatch.setenv("LYRICS_LEAD_MS", "400")
    lines, synced = lf._parse_lyrics(None, "[ar:x]\n[00:01.00]A\n[00:05.50][01:10.00]B\n[00:09.00]C")
    assert synced and [l["t"] for l in lines] == ["A", "B", "C", "B"]
    assert [l["s"] for l in lines] == [600, 5100, 8600, 69600]
    buckets = lf._lyrics_buckets(lines)
    assert buckets[0] == -1 and buckets[3] == 0 and buckets[21] == 1 and buckets[279] == 3
    assert lf._parse_lyrics("x\ny", None) == ([{"s": -1, "e": -1, "t": "x"}, {"s": -1, "e": -1, "t": "y"}], False)


# ----------------------------------------------------------------- APL document
def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def test_document_invariants():
    nodes = list(_walk(DOC))
    # the refresh loop repeats by itself, on a sequencer that touches do not stop
    loop = [n for n in nodes if n.get("sequencer") == "maRefresh"]
    assert len(loop) == 1 and loop[0]["repeatCount"] > 1000
    # commands address the runtime id of the layout root
    assert not [n for n in nodes if n.get("componentId") == "MaTimeRoot"]
    # the Video owns the values its handlers write
    video = [n for n in nodes if n.get("type") == "Video"][0]
    assert {"trackOffset", "pendingElapsed", "needsResync"} <= {b["name"] for b in video["bind"]}
    # voice "next" applied by the Echo to the Video lands on a dummy second source
    assert video["source"] == ["${audioSources}", "${audioNextSource}"]
    assert DOC["settings"]["idleTimeout"] >= 60000
