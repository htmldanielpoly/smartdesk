"""Client for the internal AI service.

Every call is best-effort: if the AI service is slow, down, or errors, we return
``None`` so the caller can fall back gracefully. Core ticketing never blocks on
AI availability (proposal: Risk Assessment / Availability).
"""
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def _post(path: str, payload: dict, priority: str | None = None) -> dict | None:
    """POST to the AI service. ``priority`` (the ticket's URGENT/HIGH/MEDIUM/
    LOW) is passed along so the AI scheduler orders the job accordingly."""
    url = f"{settings.ai_service_url}{path}"
    if priority:
        payload = {**payload, "priority": priority}
    try:
        async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("AI service call to %s failed: %s", path, exc)
        return None


async def health() -> dict | None:
    """Model state and live scheduler statistics (``GET /health``)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ai_service_url}/health")
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("AI service health check failed: %s", exc)
        return None


async def classify(title: str, description: str, priority: str | None = None) -> dict | None:
    return await _post("/classify", {"title": title, "description": description}, priority)


async def copilot(
    title: str, description: str, conversation: list[str], priority: str | None = None
) -> dict | None:
    return await _post(
        "/copilot",
        {"title": title, "description": description, "conversation": conversation},
        priority,
    )


async def duplicates(
    title: str, description: str, candidates: list[dict], priority: str | None = None
) -> dict | None:
    return await _post(
        "/duplicates",
        {"title": title, "description": description, "candidates": candidates},
        priority,
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
