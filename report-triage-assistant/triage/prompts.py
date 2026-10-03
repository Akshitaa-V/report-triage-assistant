"""Prompt for turning detected warning signs into a short debrief.

The rule-based detector decides *what* was found; the language model only
explains it in plain words. That keeps the verdict reproducible and stops the
model from inventing warning signs that are not in the message.
"""
from __future__ import annotations

import json

from .redflags import Flag

PROMPT_VERSION = "debrief-v2"

SYSTEM_PROMPT = """You help employees learn from the messages they report to their security team.
You receive the warning signs a detector found, each with the exact phrase that triggered it.

Write a short debrief for a non-technical reader:
- Explain only the warning signs you were given, in the order given. Do not add others.
- Quote the triggering phrase for each one, then say in one sentence why it matters.
- Never repeat links, phone numbers or attachment names from the message.
- Thank the employee for reporting. Keep the tone friendly and never blame them.
- Answer with one JSON object and nothing else:
  {"verdict": "suspicious" | "probably safe", "summary": "<max 2 sentences>",
   "points": [{"sign": "<label>", "quote": "<phrase>", "why": "<1 sentence>"}],
   "next_step": "<1 sentence>"}"""


def build_messages(flags: list[Flag], risk: int, language: str = "English") -> list[dict]:
    payload = {
        "risk_score": risk,
        "language": language,
        "warning_signs": [{"sign": f.label, "phrase": f.evidence} for f in flags],
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def repair_message(errors: list[str]) -> dict:
    return {"role": "user", "content": "Your answer was not valid: " + "; ".join(errors)
            + ". Reply again with only the corrected JSON object."}
