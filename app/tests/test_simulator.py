import json

import pytest

pytest.importorskip("ask_sdk_core")
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.utils import is_intent_name
from flask import Flask

from endpoints.simulator import simulator_bp


def _app(skill_id):
    sb = SkillBuilder()
    sb.skill_id = skill_id

    @sb.request_handler(can_handle_func=is_intent_name("HelloIntent"))
    def hello(handler_input):
        return handler_input.response_builder.speak("hello").response

    app = Flask(__name__)
    app.config["ALEXA_SKILL"] = sb.create()
    app.register_blueprint(simulator_bp)
    return app.test_client()


@pytest.mark.parametrize("skill_id", ["", "amzn1.ask.skill.test"])
def test_simulator_runs_the_intent_in_the_app(skill_id):
    # No HTTP round trip: the skill endpoint itself only takes requests signed by Amazon.
    r = _app(skill_id).post("/simulator/send", json={"intent": "HelloIntent"})
    answer = r.get_json()
    assert answer["status_code"] == 200, answer
    assert "hello" in json.loads(answer["body"])["response"]["outputSpeech"]["ssml"]


def test_simulator_reports_a_skill_error():
    answer = _app("").post("/simulator/send", json={"intent": "NoSuchIntent"}).get_json()
    assert answer["status_code"] == 500
