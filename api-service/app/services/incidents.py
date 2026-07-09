"""Incident overview: cluster active complaints into incidents.

The clustering itself runs on the ai-service using the local embedding model
(``POST /cluster``). If the AI service is unavailable we cluster lexically here
instead, so the overview is always available (same graceful-degradation policy
as the rest of the system). Severity comes from each ticket's *effective
priority* — which already prefers an agent-set value, then the local model's
classification (``aiSuggested``), then MEDIUM.
"""
import re
from collections import Counter

from app.database import get_db
from app.services import ai_client
from app.services.queueing import _as_utc, effective_priority

# Only active complaints are incident-relevant.
_ACTIVE_STATUSES = ["OPEN", "IN_PROGRESS"]
# A group needs at least this many reports to count as an "incident" (vs. noise).
_MIN_INCIDENT = 3
# Rough fan-out: customers likely affected per individual report. It's an
# estimate shown to the manager, not a precise figure.
_CUSTOMERS_PER_REPORT = 50

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "is", "are", "was", "were", "and", "or", "of", "to", "in",
    "on", "at", "my", "our", "we", "i", "it", "this", "that", "for", "with",
    "since", "has", "have", "had", "been", "no", "not", "here", "there", "all",
    "still", "just", "now", "please", "help", "up", "out", "off", "get", "got",
}

_SEV_RANK = {"URGENT": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}
_ACTION = {
    "URGENT": "Dispatch an emergency crew now and notify affected customers.",
    "HIGH": "Assign a field crew and monitor for escalation.",
    "MEDIUM": "Queue for standard dispatch.",
    "LOW": "Queue for standard dispatch.",
}


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 1 and t not in _STOP}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _lexical_groups(items: list[dict], threshold: float = 0.12) -> list[list[str]]:
    """Single-linkage clustering by token overlap — the AI-offline fallback."""
    toks = [_tokens(f"{it['title']} {it['description']}") for it in items]
    clusters: list[list[int]] = []
    for i in range(len(items)):
        best: list[int] | None = None
        best_score = threshold
        for cluster in clusters:
            score = max(_jaccard(toks[i], toks[j]) for j in cluster)
            if score >= best_score:
                best_score = score
                best = cluster
        if best is None:
            clusters.append([i])
        else:
            best.append(i)
    return [[items[i]["id"] for i in cluster] for cluster in clusters]


def _label(members: list[dict]) -> tuple[str, str | None]:
    """Derive a human label + likely location from the cluster's own words."""
    words: list[str] = []
    for m in members:
        words += [
            w for w in _TOKEN_RE.findall(f"{m['title']} {m['description']}".lower())
            if len(w) > 2 and w not in _STOP
        ]
    common = [w for w, _ in Counter(words).most_common(4)]
    if not common:
        return "Incident", None
    location = common[0].title()
    label = " · ".join(w.title() for w in common[:3])
    return label, location


async def overview() -> dict:
    """Cluster active tickets into incidents and roll up a manager overview."""
    tickets = [t async for t in get_db().tickets.find({"status": {"$in": _ACTIVE_STATUSES}})]
    by_id = {str(t["_id"]): t for t in tickets}
    items = [
        {"id": str(t["_id"]), "title": t["title"], "description": t["description"]}
        for t in tickets
    ]

    ai = await ai_client.cluster(items) if items else None
    if ai and isinstance(ai.get("groups"), list):
        groups = ai["groups"]
        source = ai.get("source", "local")
    else:
        groups = _lexical_groups(items)
        source = "fallback"

    incidents: list[dict] = []
    clustered_ids: set[str] = set()
    for group in groups:
        members = [by_id[i] for i in group if i in by_id]
        if len(members) < _MIN_INCIDENT:
            continue
        clustered_ids.update(str(m["_id"]) for m in members)
        severity = max(
            (effective_priority(m) for m in members),
            key=lambda p: _SEV_RANK.get(p, 0),
        )
        label, location = _label(members)
        incidents.append({
            "label": label,
            "location": location,
            "severity": severity,
            "report_count": len(members),
            "customers_est": len(members) * _CUSTOMERS_PER_REPORT,
            "first_report": min(_as_utc(m["createdAt"]) for m in members),
            "recommended": _ACTION.get(severity, _ACTION["MEDIUM"]),
            "samples": [m["title"] for m in members[:3]],
            "ticket_ids": [str(m["_id"]) for m in members],
        })

    incidents.sort(
        key=lambda inc: (_SEV_RANK.get(inc["severity"], 0), inc["report_count"]),
        reverse=True,
    )
    noise = [t for t in tickets if str(t["_id"]) not in clustered_ids]
    return {
        "source": source,
        "total_complaints": len(tickets),
        "clustered": len(clustered_ids),
        "incident_count": len(incidents),
        "noise_count": len(noise),
        "customers_est": sum(inc["customers_est"] for inc in incidents),
        "incidents": incidents,
        "noise_samples": [t["title"] for t in noise[:5]],
    }
