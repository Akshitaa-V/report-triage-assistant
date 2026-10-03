"""Finds common warning signs in a message an employee has reported.

Each match is kept with the text that triggered it, so the debrief shown to
the employee can point at the exact phrase instead of giving generic advice.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

FLAG_PATTERNS: dict[str, list[str]] = {
    "urgency": [
        r"\bwithin (the next )?\d+ (minutes|hours?)\b", r"\bimmediately\b",
        r"\burgent(ly)?\b", r"\bend of (the )?day\b", r"\blast chance\b",
    ],
    "authority": [r"\b(ceo|cfo|managing director|head of \w+|it security team)\b"],
    "payment_change": [
        r"\b(new|updated|changed) (bank|account|iban|payment) details\b",
        r"\bgift cards?\b", r"\bwire transfer\b",
    ],
    "credential_request": [
        r"\b(verify|confirm|re-?enter) your (login|password|credentials)\b",
        r"\b(one-time|verification) code\b",
    ],
    "secrecy": [r"\bkeep this (confidential|between us)\b", r"\bdo not tell\b"],
    "generic_greeting": [r"^\s*(dear (user|customer|employee)|hello there)\b"],
    "threat": [r"\b(will be|gets?) (suspended|locked|deactivated|deleted)\b"],
}

LABELS = {
    "urgency": "Time pressure",
    "authority": "Appeal to authority",
    "payment_change": "Unusual payment request",
    "credential_request": "Request for login details or codes",
    "secrecy": "Request for secrecy",
    "generic_greeting": "Generic greeting",
    "threat": "Threat of consequences",
    "sender_mismatch": "Sender outside your organisation",
}

_COMPILED = {k: [re.compile(p, re.I | re.M) for p in v] for k, v in FLAG_PATTERNS.items()}


@dataclass(frozen=True)
class Flag:
    name: str
    evidence: str

    @property
    def label(self) -> str:
        return LABELS[self.name]


def detect(text: str, sender: str = "", org_domain: str = "") -> list[Flag]:
    flags: list[Flag] = []
    for name, patterns in _COMPILED.items():
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                flags.append(Flag(name, match.group(0).strip()))
                break
    if sender and org_domain and "@" in sender:
        domain = sender.rsplit("@", 1)[1].strip(" >").lower()
        if domain != org_domain.lower():
            flags.append(Flag("sender_mismatch", domain))
    return flags


def risk_score(flags: list[Flag]) -> int:
    """0-100. Weighted so that a credential or payment request alone is high."""
    weights = {"credential_request": 40, "payment_change": 40, "sender_mismatch": 20,
               "urgency": 15, "authority": 15, "secrecy": 20, "threat": 15,
               "generic_greeting": 5}
    return min(100, sum(weights[f.name] for f in flags))
