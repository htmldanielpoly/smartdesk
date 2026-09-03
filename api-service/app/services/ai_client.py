"""Client for the internal AI service.

Every call is best-effort: if the AI service is slow, down, or errors, we return
``None`` so the caller can fall back gracefully. Core ticketing never blocks on
AI availability (proposal: Risk Assessment / Availability).
"""
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def _post(path: str, payload: dict) -> dict | None:
    url = f"{settings.ai_service_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("AI service call to %s failed: %s", path, exc)
        return None


async def classify(title: str, description: str) -> dict | None:
    return await _post("/classify", {"title": title, "description": description})


async def copilot(title: str, description: str, conversation: list[str]) -> dict | None:
    return await _post(
        "/copilot",
        {"title": title, "description": description, "conversation": conversation},
    )


async def duplicates(title: str, description: str, candidates: list[dict]) -> dict | None:
    return await _post(
        "/duplicates",
        {"title": title, "description": description, "candidates": candidates},
    )


async def auto_resolve(title: str, description: str, candidates: list[dict]) -> dict | None:
    """Long-term memory: ask whether the ticket repeats a resolved one.

    ``candidates`` is a list of {ticket_id, title, description, resolution}.
    Returns {resolved, match, draft_response, threshold, source, flags} or
    None if the AI service is unavailable (the ticket then simply stays in
    the agent queue).
    """
    return await _post(
        "/auto-resolve",
        {"title": title, "description": description, "candidates": candidates},
    )


async def cluster(items: list[dict]) -> dict | None:
    """Group a batch of tickets into incidents via the local embedding model.

    ``items`` is a list of {id, title, description}. Returns {groups, source}
    or None if the AI service is unavailable (caller falls back to lexical
    clustering).
    """
    return await _post("/cluster", {"items": items})
