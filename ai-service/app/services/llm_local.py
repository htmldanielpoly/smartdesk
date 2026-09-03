"""Inference wrapper around the local llama.cpp models.

Anti-hallucination by construction: every chat call is constrained by a JSON
schema that llama.cpp compiles into a decoding grammar — the model is
physically unable to emit anything but JSON matching the schema (including
enum fields, so an invalid ticket category cannot even be sampled).

Concurrency: a llama.cpp model instance is not safe for concurrent calls,
but the *two* instances are independent. Each has its own lock, so a chat
completion and an embedding run in parallel on different cores; the
scheduler (services/scheduler.py) decides which jobs get to run and in what
order. Embeddings take the lock per text, so a long batch (incident
clustering of 200 tickets) cannot starve a single high-priority lookup.

Returns None on any failure so callers can fall back to rule-based logic.
"""
import json
import logging
import threading

from app.config import settings
from app.services import model_manager

logger = logging.getLogger(__name__)

_chat_lock = threading.Lock()
_embed_lock = threading.Lock()


def chat_json(system: str, user: str, schema: dict) -> dict | None:
    """Run a chat completion whose output is grammar-constrained to ``schema``.

    Returns the parsed JSON dict, or None if the model is unavailable or
    anything goes wrong.
    """
    model = model_manager.get_chat_model()
    if model is None:
        return None
    try:
        with _chat_lock:
            resp = model.create_chat_completion(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object", "schema": schema},
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_output_tokens,
            )
        raw = resp["choices"][0]["message"]["content"]
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - degrade gracefully on any failure
        logger.warning("Local chat inference failed: %s", exc)
        return None


def embed(texts: list[str]) -> list[list[float]] | None:
    """Embed ``texts`` with the local embedding model, or None if unavailable."""
    model = model_manager.get_embed_model()
    if model is None or not texts:
        return None
    try:
        out: list[list[float]] = []
        for text in texts:
            with _embed_lock:  # released between texts: other jobs can interleave
                out.append(model.embed(text))
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("Local embedding failed: %s", exc)
        return None
