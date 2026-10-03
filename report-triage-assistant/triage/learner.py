"""Tracks what each employee is good at spotting, to pick their next lesson.

Every report is resolved by the security team as a correct report or a false
alarm; messages that reached the employee and were not reported count as
missed. For each warning sign we keep a smoothed hit rate and recommend the
sign with the lowest one as the next micro-lesson.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

PRIOR_HITS, PRIOR_TOTAL = 1.0, 2.0  # start every sign at 50 %


@dataclass
class LearnerStats:
    hits: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    seen: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    false_alarms: int = 0

    def rate(self, sign: str) -> float:
        return (self.hits[sign] + PRIOR_HITS) / (self.seen[sign] + PRIOR_TOTAL)


class LearnerTracker:
    def __init__(self) -> None:
        self._learners: dict[str, LearnerStats] = defaultdict(LearnerStats)

    def record(self, learner_id: str, flags: list[str], outcome: str) -> None:
        if outcome not in ("reported", "missed", "false_alarm"):
            raise ValueError(f"unknown outcome {outcome!r}")
        stats = self._learners[learner_id]
        if outcome == "false_alarm":
            stats.false_alarms += 1
            return
        for sign in flags:
            stats.seen[sign] += 1
            if outcome == "reported":
                stats.hits[sign] += 1

    def next_lesson(self, learner_id: str, signs: list[str]) -> str:
        stats = self._learners[learner_id]
        return min(signs, key=lambda s: (stats.rate(s), s))

    def summary(self, learner_id: str, signs: list[str]) -> dict:
        stats = self._learners[learner_id]
        return {"rates": {s: round(stats.rate(s), 2) for s in signs},
                "false_alarms": stats.false_alarms,
                "next_lesson": self.next_lesson(learner_id, signs)}
