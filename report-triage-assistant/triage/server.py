"""Small webhook API (standard library only) that n8n calls.

POST /report   {"learner_id", "sender", "subject", "body"} -> debrief JSON
POST /outcome  {"learner_id", "flags": [...], "outcome"}    -> learner summary
GET  /health
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .debrief import make_debrief, openai_compatible_llm
from .learner import LearnerTracker
from .redflags import LABELS

ORG_DOMAIN = os.environ.get("ORG_DOMAIN", "example-company.test")
TRACKER = LearnerTracker()
LLM = openai_compatible_llm()


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send(200, {"status": "ok", "llm": LLM is not None})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"error": "body must be JSON"})
        if self.path == "/report":
            if not body.get("body"):
                return self._send(422, {"error": "field 'body' is required"})
            return self._send(200, make_debrief(body, ORG_DOMAIN, LLM))
        if self.path == "/outcome":
            try:
                TRACKER.record(body["learner_id"], body.get("flags", []), body["outcome"])
            except (KeyError, ValueError) as exc:
                return self._send(422, {"error": str(exc)})
            return self._send(200, TRACKER.summary(body["learner_id"], list(LABELS)))
        self._send(404, {"error": "not found"})

    def log_message(self, *args) -> None:
        pass


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    print(f"listening on :{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
