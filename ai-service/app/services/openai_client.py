"""Thin wrapper around the OpenAI client.

Returns None on any error so callers can fall back to rule-based logic. If no
API key is configured, the client is simply disabled.
"""
import logging

from app.config import settings

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if not settings.ai_enabled:
        return None
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


def chat(system: str, user: str) -> str | None:
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
        return resp.choices[0].message.content
    except Exception as exc:  # noqa: BLE001 - degrade gracefully on any failure
        logger.warning("OpenAI chat call failed: %s", exc)
        return None


def embed(texts: list[str]) -> list[list[float]] | None:
    client = _get_client()
    if client is None or not texts:
        return None
    try:
        resp = client.embeddings.create(
            model=settings.openai_embedding_model, input=texts
        )
        return [item.embedding for item in resp.data]
    except Exception as exc:  # noqa: BLE001
        logger.warning("OpenAI embedding call failed: %s", exc)
        return None
