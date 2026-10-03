import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from triage import debrief, server
from triage.learner import LearnerTracker
from triage.redflags import detect, risk_score

ORG = "example-company.test"


def names(flags):
    return {f.name for f in flags}


# ---------- detector ----------
@pytest.mark.parametrize("text,expected", [
    ("Please reply immediately", "urgency"),
    ("Message from the CFO", "authority"),
    ("We have new bank details for you", "payment_change"),
    ("Please confirm your password", "credential_request"),
    ("Keep this confidential", "secrecy"),
    ("Dear user, a note", "generic_greeting"),
    ("Your mailbox will be locked", "threat"),
])
def test_detects_each_sign(text, expected):
    assert expected in names(detect(text))


def test_plain_message_has_no_signs():
    assert detect("Lunch is at 12:30 in the canteen, see you there.") == []


def test_sender_mismatch_only_for_outside_domain():
    assert "sender_mismatch" in names(detect("hi", "a@other.test", ORG))
    assert "sender_mismatch" not in names(detect("hi", f"a@{ORG}", ORG))


def test_evidence_is_the_matching_phrase():
    flag = detect("Please act URGENTLY now")[0]
    assert flag.evidence.lower() == "urgently"


def test_risk_score_capped():
    flags = detect("CFO: urgent, confirm your password, new bank details, keep this confidential",
                   "x@other.test", ORG)
    assert risk_score(flags) == 100


# ---------- debrief ----------
MSG = {"sender": "it@other.test", "subject": "Urgent", "body": "Please confirm your password."}


def test_template_debrief_offline():
    out = debrief.make_debrief(MSG, ORG)
    assert out["source"] == "template" and out["verdict"] == "suspicious"
    assert {p["sign"] for p in out["points"]} >= {"Time pressure", "Request for login details or codes"}


def test_safe_message_is_probably_safe():
    out = debrief.make_debrief({"sender": f"a@{ORG}", "body": "Team lunch at noon."}, ORG)
    assert out["verdict"] == "probably safe" and out["points"] == []


def _good_answer(flags_labels):
    return json.dumps({"verdict": "suspicious", "summary": "Thanks.", "next_step": "Wait.",
                       "points": [{"sign": s, "quote": "q", "why": "w"} for s in flags_labels]})


def test_llm_answer_used_when_valid():
    labels = [f.label for f in detect("Urgent\nPlease confirm your password.", MSG["sender"], ORG)]
    out = debrief.make_debrief(MSG, ORG, llm=lambda m: _good_answer(labels))
    assert out["source"] == "llm"


def test_llm_repaired_after_invalid_json():
    labels = [f.label for f in detect("Urgent\nPlease confirm your password.", MSG["sender"], ORG)]
    calls = []

    def fake(messages):
        calls.append(messages)
        return "not json" if len(calls) == 1 else _good_answer(labels)

    out = debrief.make_debrief(MSG, ORG, llm=fake)
    assert out["source"] == "llm" and len(calls) == 2
    assert "not valid" in calls[1][-1]["content"]


def test_invented_sign_rejected_then_template_fallback():
    out = debrief.make_debrief(MSG, ORG, llm=lambda m: _good_answer(["Made up sign"]))
    assert out["source"] == "template"


def test_links_in_answer_rejected():
    errors = debrief.validate({"verdict": "suspicious", "summary": "see http://x", "points": [],
                               "next_step": "."}, [])
    assert any("links" in e for e in errors)


def test_code_fenced_json_accepted():
    labels = [f.label for f in detect("Urgent\nPlease confirm your password.", MSG["sender"], ORG)]
    out = debrief.make_debrief(MSG, ORG, llm=lambda m: "```json\n" + _good_answer(labels) + "\n```")
    assert out["source"] == "llm"


# ---------- learner tracking ----------
def test_next_lesson_is_weakest_sign():
    t = LearnerTracker()
    for _ in range(3):
        t.record("a", ["urgency"], "reported")
        t.record("a", ["authority"], "missed")
    assert t.next_lesson("a", ["urgency", "authority"]) == "authority"


def test_false_alarm_counted_separately():
    t = LearnerTracker()
    t.record("a", [], "false_alarm")
    assert t.summary("a", ["urgency"])["false_alarms"] == 1


def test_unknown_outcome_raises():
    with pytest.raises(ValueError):
        LearnerTracker().record("a", [], "clicked twice")


# ---------- HTTP API ----------
@pytest.fixture()
def base_url():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def _post(url, payload):
    req = urllib.request.Request(url, json.dumps(payload).encode(),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def test_health(base_url):
    with urllib.request.urlopen(base_url + "/health") as r:
        assert json.load(r)["status"] == "ok"


def test_report_endpoint(base_url):
    status, out = _post(base_url + "/report", MSG)
    assert status == 200 and out["verdict"] == "suspicious"


def test_report_requires_body(base_url):
    assert _post(base_url + "/report", {"subject": "x"})[0] == 422


def test_outcome_endpoint(base_url):
    status, out = _post(base_url + "/outcome",
                        {"learner_id": "u1", "flags": ["urgency"], "outcome": "missed"})
    assert status == 200 and out["next_lesson"] == "urgency"
