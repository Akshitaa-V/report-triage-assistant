"""Builds the debrief for a reported message.

With an LLM configured, the model writes the explanation and its JSON is
validated; one repair round is attempted before falling back to the
template. Without an LLM the template is used directly, so the service and
tests run offline.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Callable

from . import prompts
from .redflags import Flag, detect, risk_score

LLM = Callable[[list[dict]], str]
SUSPICIOUS_AT = 40


WHY = {
    "urgency": "Pressure to act fast leaves no time to check whether the request is real.",
    "authority": "Naming a senior person makes it feel risky to say no or to ask questions.",
    "payment_change": "Changed payment details should always be confirmed by phone on a known number.",
    "credential_request": "Your own IT team will never ask for your password or a login code.",
    "secrecy": "Asking you not to tell anyone stops colleagues from spotting the problem.",
    "generic_greeting": "A real colleague or supplier usually knows your name.",
    "threat": "Threats of lost access are used to make you click before you think.",
    "sender_mismatch": "The message came from outside your organisation's domain.",
}


def template_debrief(flags: list[Flag], risk: int) -> dict:
    verdict = "suspicious" if risk >= SUSPICIOUS_AT else "probably safe"
    points = [{"sign": f.label, "quote": f.evidence, "why": WHY[f.name]} for f in flags]
    summary = (f"Thanks for reporting. We found {len(flags)} warning sign(s)."
               if flags else "Thanks for reporting. We found no typical warning signs.")
    return {"verdict": verdict, "summary": summary, "points": points,
            "next_step": "Do not reply or click; the security team will follow up."
            if verdict == "suspicious" else "If anything still feels off, ask the security team."}


def validate(answer: dict, flags: list[Flag]) -> list[str]:
    errors = []
    for key in ("verdict", "summary", "points", "next_step"):
        if key not in answer:
            errors.append(f"missing key {key!r}")
    if answer.get("verdict") not in ("suspicious", "probably safe"):
        errors.append("verdict must be 'suspicious' or 'probably safe'")
    allowed = {f.label for f in flags}
    for point in answer.get("points", []):
        if point.get("sign") not in allowed:
            errors.append(f"sign {point.get('sign')!r} was not detected; explain only the given signs")
    if "http" in json.dumps(answer).lower():
        errors.append("do not include links")
    return errors


def _parse(raw: str) -> dict | None:
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def make_debrief(message: dict, org_domain: str, llm: LLM | None = None) -> dict:
    started = time.perf_counter()
    text = f"{message.get('subject', '')}\n{message.get('body', '')}"
    flags = detect(text, message.get("sender", ""), org_domain)
    risk = risk_score(flags)
    source, answer = "template", None

    if llm is not None:
        chat = prompts.build_messages(flags, risk, message.get("language", "English"))
        for _ in range(2):  # first try + one repair round
            parsed = _parse(llm(chat))
            errors = ["answer was not a JSON object"] if parsed is None else validate(parsed, flags)
            if not errors:
                answer, source = parsed, "llm"
                break
            chat = chat + [prompts.repair_message(errors)]
    if answer is None:
        answer = template_debrief(flags, risk)

    answer.update({
        "risk_score": risk,
        "flags": [f.name for f in flags],
        "source": source,
        "prompt_version": prompts.PROMPT_VERSION,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    })
    return answer


def openai_compatible_llm() -> LLM | None:
    """Any OpenAI-compatible endpoint, set via LLM_BASE_URL, LLM_API_KEY, LLM_MODEL."""
    base = os.environ.get("LLM_BASE_URL")
    if not base:
        return None

    def call(messages: list[dict]) -> str:
        body = json.dumps({"model": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
                           "messages": messages, "temperature": 0.2,
                           "response_format": {"type": "json_object"}}).encode()
        req = urllib.request.Request(f"{base.rstrip('/')}/chat/completions", data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ.get('LLM_API_KEY', '')}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)["choices"][0]["message"]["content"]

    return call
