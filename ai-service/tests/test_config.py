"""Settings must tolerate the empty strings docker-compose passes for unset
optional knobs (e.g. ``LLM_THREADS: ${LLM_THREADS:-}``); an empty value must
mean "not set", not a crash at import time."""
from app.config import Settings


def test_empty_optional_env_values_are_ignored(monkeypatch):
    monkeypatch.setenv("LLM_THREADS", "")
    monkeypatch.setenv("AI_WORKERS", "")
    s = Settings()
    assert s.llm_threads is None
    assert s.ai_workers == Settings.model_fields["ai_workers"].default


def test_set_values_still_apply(monkeypatch):
    monkeypatch.setenv("LLM_THREADS", "3")
    monkeypatch.setenv("AI_WORKERS", "2")
    s = Settings()
    assert s.llm_threads == 3 and s.ai_workers == 2
