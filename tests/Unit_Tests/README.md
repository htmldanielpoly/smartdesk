# Unit Tests

> *Unit testing: check each class/function of the software in isolation from the
> rest of the project, to see whether it works as intended. Tests should be
> independent of the code itself, so they aren't biased toward the existing
> implementation.*

Unit tests live **next to the code they test**, in each service's `tests/`
folder, so they run in that service's environment with a single `pytest`:

| File | Unit under test |
|---|---|
| `api-service/tests/test_queueing.py` | queue scoring: priority order, aging anti-starvation, SLA-breach bonus, naive/aware datetime handling |
| `api-service/tests/test_security.py` | password hashing round-trip, JWT sign/verify, tamper rejection |
| `api-service/tests/test_status_transitions.py` | ticket status state machine (`can_transition`) |
| `ai-service/tests/test_guardrails.py` | input sanitization, injection detection, label whitelisting |
| `ai-service/tests/test_fallback.py` | deterministic rule-based classification when the LLM is off |

Run them:

```bash
cd api-service && pytest tests/test_queueing.py tests/test_security.py tests/test_status_transitions.py
cd ai-service  && pytest tests/test_guardrails.py tests/test_fallback.py
```
