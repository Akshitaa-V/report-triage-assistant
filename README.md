# Report Triage Assistant

When an employee reports a suspicious message, they usually hear nothing back. This service closes that loop: it finds the warning signs in the reported message, writes a short, friendly debrief that quotes the exact phrases, and tracks which signs each person tends to miss so the next training lesson targets that gap.

An n8n workflow connects it to the reporting mailbox, the security team's chat and email.

## How it works

```
reported message -> n8n webhook -> POST /report -> detector (rules) -> risk score
                                                  -> debrief (LLM or template, validated)
                 -> suspicious? -> notify security team -> email debrief to employee
security team resolves report -> POST /outcome -> per-person hit rates -> next lesson
```

- **Detector** (`triage/redflags.py`): eight warning signs (time pressure, authority, payment change, request for login details or codes, secrecy, generic greeting, threats, outside sender), each returned with the phrase that triggered it.
- **Debrief** (`triage/debrief.py`, `triage/prompts.py`): the detector decides *what* was found; the language model only explains it. The prompt asks for strict JSON, and the answer is rejected if it names a sign the detector did not find or contains a link. One repair round sends the errors back to the model; after that, a template debrief is used. Works with any OpenAI-compatible endpoint and fully offline without one.
- **Learner tracking** (`triage/learner.py`): smoothed hit rate per person and warning sign; false alarms are counted separately so people are not discouraged from reporting.
- **API** (`triage/server.py`): standard-library HTTP server, no dependencies.

## Run

```bash
python -m triage.server                      # offline, template debriefs
LLM_BASE_URL=https://api.openai.com/v1 LLM_API_KEY=... LLM_MODEL=gpt-4o-mini python -m triage.server

curl -X POST localhost:8080/report -H "Content-Type: application/json" \
  -d '{"sender":"it@other.test","subject":"Urgent","body":"Please confirm your password."}'
```

Import `n8n/report_triage_workflow.json` into n8n and set `TRIAGE_URL`.

## Tests

```bash
pip install pytest
python -m pytest -q        # 25 tests: detector, debrief validation and repair, learner tracking, HTTP API
```

## Design notes

- Rules first, model second: the verdict is reproducible and testable, and the model cannot invent warning signs.
- Prompt is versioned (`PROMPT_VERSION`) and returned with every debrief, so answers can be compared across prompt changes.
- Never repeating links or phone numbers from the reported message in the debrief is enforced in code, not only in the prompt.
