"""Long-term memory: automated resolution of exact duplicates.

Once a ticket has been resolved by a human agent, the answer is remembered.
When another client later submits the *same* problem, the AI answers it
itself - no agent in the loop. This module decides whether a new ticket is
such a repeat and drafts the reply; the api-service owns the data and posts
the reply / closes the ticket.

Safety properties (this path acts autonomously, so it is deliberately strict):

* **Very high similarity bar** - the cosine threshold (default 0.95) is far
  above duplicate *detection* (0.55). Paraphrases are merely flagged to an
  agent; only near-identical re-submissions are answered automatically.
* **Grounded by construction** - the reply reuses the stored, human-written
  resolution verbatim. The LLM is not asked to generate anything, so there
  is nothing to hallucinate.
* **Jailbreak-aware** - tickets that trip the injection detector are never
  auto-answered; they go to a human like any other suspicious ticket.
* **Reversible** - the customer can reopen the ticket, which sends it to the
  agent queue (handled by the api-service).
"""
from app.config import settings
from app.schemas import AutoResolveMatch, AutoResolveRequest, AutoResolveResponse
from app.services import duplicates, guardrails

_REPLY_TEMPLATE = (
    "Hi,\n\n"
    "Thanks for reaching out about \"{title}\". This looks identical to a "
    "problem we have already solved for another customer, so here is the "
    "solution that worked:\n\n"
    "{resolution}\n\n"
    "If this does not fix it, simply reopen the ticket and a support agent "
    "will take over.\n\n"
    "Best regards,\nSmartDesk AI (on behalf of the Support Team)"
)


def draft_reply(title: str, resolution: str) -> str:
    """Customer-facing reply built around a stored (human-written) resolution.

    The resolution is sanitized like any ticket text before it is sent back,
    so a stored answer can never smuggle chat-template tokens or control
    characters into a reply."""
    clean_title = guardrails.sanitize(title, settings.max_title_chars)
    clean_resolution = guardrails.sanitize(resolution, settings.max_description_chars)
    return _REPLY_TEMPLATE.format(title=clean_title, resolution=clean_resolution)


def _threshold(source: str) -> float:
    if source == "local":
        return settings.auto_resolve_similarity_threshold
    return settings.auto_resolve_fallback_threshold


def _not_resolved(flag: str, source: str = "fallback", match=None) -> AutoResolveResponse:
    return AutoResolveResponse(
        resolved=False, match=match, threshold=_threshold(source), source=source, flags=[flag]
    )


def auto_resolve(req: AutoResolveRequest) -> AutoResolveResponse:
    """Decide whether ``req`` repeats an already-resolved ticket.

    Returns ``resolved=True`` with the best match and a drafted reply when the
    top candidate clears the (path-specific) threshold; otherwise
    ``resolved=False`` with a flag explaining why.
    """
    if not settings.auto_resolve_enabled:
        return _not_resolved("disabled")

    title, description = guardrails.sanitize_ticket(req.title, req.description)
    threats = guardrails.threat_flags(title, description)
    if threats:
        # A ticket trying to steer or pressure the AI is handled by a human.
        return AutoResolveResponse(
            resolved=False, threshold=_threshold("fallback"), source="fallback", flags=threats
        )

    # Only candidates that actually carry an answer can resolve anything.
    candidates = [c for c in req.candidates if c.resolution.strip()]
    if not candidates:
        return _not_resolved("no_candidates")

    query_text = f"{title}. {description}"
    cand_texts = [f"{c.title}. {c.description}" for c in candidates]
    scores, source = duplicates.similarities(query_text, cand_texts)

    best_idx = max(range(len(candidates)), key=lambda i: scores[i])
    best = candidates[best_idx]
    match = AutoResolveMatch(
        ticket_id=best.ticket_id, title=best.title, similarity=round(scores[best_idx], 3)
    )

    if scores[best_idx] < _threshold(source):
        return _not_resolved("below_threshold", source, match)

    return AutoResolveResponse(
        resolved=True,
        match=match,
        draft_response=draft_reply(title, best.resolution),
        threshold=_threshold(source),
        source=source,
        flags=[],
    )
