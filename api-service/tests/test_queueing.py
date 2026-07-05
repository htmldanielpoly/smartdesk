"""Pure unit tests for the queue scoring logic (no app, no client, no db)."""
from datetime import UTC, datetime, timedelta

from bson import ObjectId

from app.services.queueing import (
    AGING_POINTS_PER_HOUR,
    PRIORITY_WEIGHT,
    SLA_BREACH_BONUS,
    SLA_HOURS,
    build_queue_entry,
    effective_priority,
    priority_score,
    sla_deadline,
)

NOW = datetime(2026, 7, 5, 12, 0, 0, tzinfo=UTC)


def make_ticket(created_at, priority=None, ai_priority=None, assigned=None):
    return {
        "_id": ObjectId(),
        "title": "test ticket",
        "description": "desc",
        "status": "OPEN",
        "createdBy": ObjectId(),
        "assignedAgent": assigned,
        "category": None,
        "priority": priority,
        "department": None,
        "aiSuggested": {"priority": ai_priority, "status": "ok"},
        "createdAt": created_at,
        "updatedAt": created_at,
    }


def test_priority_ordering_at_equal_age():
    """At equal (zero) age, URGENT > HIGH > MEDIUM > LOW."""
    scores = {
        p: priority_score(make_ticket(NOW, priority=p), NOW)
        for p in ("URGENT", "HIGH", "MEDIUM", "LOW")
    }
    assert scores["URGENT"] > scores["HIGH"] > scores["MEDIUM"] > scores["LOW"]


def test_aging_lifts_old_low_above_fresh_medium():
    """Aging prevents starvation: an old LOW overtakes a fresh MEDIUM.

    Crossover: LOW starts PRIORITY_WEIGHT[MEDIUM] - PRIORITY_WEIGHT[LOW] = 20
    points behind and gains AGING_POINTS_PER_HOUR = 2/h, so it draws level
    after exactly 10 hours of waiting.
    """
    crossover_hours = (
        PRIORITY_WEIGHT["MEDIUM"] - PRIORITY_WEIGHT["LOW"]
    ) / AGING_POINTS_PER_HOUR
    assert crossover_hours == 10.0

    fresh_medium = make_ticket(NOW, priority="MEDIUM")

    young_low = make_ticket(NOW - timedelta(hours=crossover_hours - 1), priority="LOW")
    old_low = make_ticket(NOW - timedelta(hours=crossover_hours + 1), priority="LOW")

    assert priority_score(young_low, NOW) < priority_score(fresh_medium, NOW)
    assert priority_score(old_low, NOW) > priority_score(fresh_medium, NOW)


def test_sla_breach_bonus_jumps_queue():
    """A breached MEDIUM outranks even a fresh URGENT thanks to the bonus."""
    breached_medium = make_ticket(
        NOW - timedelta(hours=SLA_HOURS["MEDIUM"] + 1), priority="MEDIUM"
    )
    fresh_urgent = make_ticket(NOW, priority="URGENT")

    breached_score = priority_score(breached_medium, NOW)
    assert breached_score >= SLA_BREACH_BONUS
    assert breached_score > priority_score(fresh_urgent, NOW)

    # Just inside the SLA there is no bonus yet.
    inside_sla = make_ticket(
        NOW - timedelta(hours=SLA_HOURS["MEDIUM"] - 1), priority="MEDIUM"
    )
    assert priority_score(inside_sla, NOW) < SLA_BREACH_BONUS


def test_effective_priority_fallback_chain():
    # Agent-set priority wins over the AI suggestion.
    assert effective_priority(make_ticket(NOW, priority="HIGH", ai_priority="LOW")) == "HIGH"
    # No agent priority -> AI suggestion.
    assert effective_priority(make_ticket(NOW, ai_priority="URGENT")) == "URGENT"
    # Neither set -> MEDIUM.
    assert effective_priority(make_ticket(NOW)) == "MEDIUM"


def test_effective_priority_rejects_junk_values():
    # Junk agent priority falls through to a valid AI suggestion.
    assert effective_priority(make_ticket(NOW, priority="banana", ai_priority="LOW")) == "LOW"
    # Junk everywhere -> MEDIUM.
    assert effective_priority(make_ticket(NOW, priority="banana", ai_priority="!!")) == "MEDIUM"
    # aiSuggested missing entirely (or None) must not crash.
    ticket = make_ticket(NOW)
    del ticket["aiSuggested"]
    assert effective_priority(ticket) == "MEDIUM"
    ticket["aiSuggested"] = None
    assert effective_priority(ticket) == "MEDIUM"


def test_naive_and_aware_created_at_score_identically():
    """Mongo may hand back naive UTC datetimes; both forms must score equally."""
    created_aware = NOW - timedelta(hours=5)
    created_naive = created_aware.replace(tzinfo=None)

    aware_ticket = make_ticket(created_aware, priority="HIGH")
    naive_ticket = make_ticket(created_naive, priority="HIGH")

    assert priority_score(aware_ticket, NOW) == priority_score(naive_ticket, NOW)
    assert sla_deadline(naive_ticket, "HIGH") == sla_deadline(aware_ticket, "HIGH")


def test_sla_deadline_is_created_at_plus_sla_hours():
    ticket = make_ticket(NOW, priority="URGENT")
    assert sla_deadline(ticket, "URGENT") == NOW + timedelta(hours=SLA_HOURS["URGENT"])


def test_build_queue_entry_fields():
    created = NOW - timedelta(hours=SLA_HOURS["LOW"] + 2)  # breached LOW
    ticket = make_ticket(created, priority="LOW")
    entry = build_queue_entry(ticket, NOW)

    assert entry["effective_priority"] == "LOW"
    assert entry["score"] == priority_score(ticket, NOW)
    assert entry["sla_deadline"] == created + timedelta(hours=SLA_HOURS["LOW"])
    assert entry["sla_breached"] is True
    assert entry["waiting"] is True
    # Original ticket fields are preserved.
    assert entry["_id"] == ticket["_id"]

    assigned = build_queue_entry(make_ticket(NOW, assigned=ObjectId()), NOW)
    assert assigned["waiting"] is False
    assert assigned["sla_breached"] is False
