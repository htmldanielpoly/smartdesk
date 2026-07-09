"""Unit tests — one piece of logic in isolation, no app/DB/network.

These import the domain functions directly and assert their behavior from the
documented constants (not a golden number copied out of the implementation), so
the tests stay independent of how the code happens to be written.

The full unit suite also lives per-service (see ../Unit_Tests/README.md); these
are representative examples in the lecture's taxonomy layout.
"""
from datetime import UTC, datetime, timedelta

from app.models.enums import TicketStatus, can_transition
from app.services.queueing import (
    AGING_POINTS_PER_HOUR,
    PRIORITY_WEIGHT,
    SLA_BREACH_BONUS,
    SLA_HOURS,
    effective_priority,
    priority_score,
    sla_deadline,
)

NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)


def _ticket(created, priority=None, ai_priority=None):
    return {
        "createdAt": created,
        "priority": priority,
        "aiSuggested": {"priority": ai_priority, "status": "ok"},
    }


def test_priority_ordering_at_equal_age():
    scores = {p: priority_score(_ticket(NOW, priority=p), NOW) for p in PRIORITY_WEIGHT}
    assert scores["URGENT"] > scores["HIGH"] > scores["MEDIUM"] > scores["LOW"]


def test_effective_priority_fallback_chain():
    # Agent-set wins over the AI suggestion; then AI; then MEDIUM.
    assert effective_priority(_ticket(NOW, priority="HIGH", ai_priority="LOW")) == "HIGH"
    assert effective_priority(_ticket(NOW, ai_priority="URGENT")) == "URGENT"
    assert effective_priority(_ticket(NOW)) == "MEDIUM"
    # Junk values are never trusted.
    assert effective_priority(_ticket(NOW, priority="banana")) == "MEDIUM"


def test_aging_prevents_starvation():
    # A LOW starts PRIORITY_WEIGHT gap behind MEDIUM and closes it via aging.
    crossover = (PRIORITY_WEIGHT["MEDIUM"] - PRIORITY_WEIGHT["LOW"]) / AGING_POINTS_PER_HOUR
    old_low = _ticket(NOW - timedelta(hours=crossover + 1), priority="LOW")
    fresh_medium = _ticket(NOW, priority="MEDIUM")
    assert priority_score(old_low, NOW) > priority_score(fresh_medium, NOW)


def test_breached_sla_jumps_the_queue():
    breached = _ticket(NOW - timedelta(hours=SLA_HOURS["MEDIUM"] + 1), priority="MEDIUM")
    assert priority_score(breached, NOW) >= SLA_BREACH_BONUS
    assert sla_deadline(breached, "MEDIUM") == (
        NOW - timedelta(hours=SLA_HOURS["MEDIUM"] + 1) + timedelta(hours=SLA_HOURS["MEDIUM"])
    )


def test_status_machine_allows_and_blocks_transitions():
    assert can_transition(TicketStatus.OPEN, TicketStatus.IN_PROGRESS)
    assert can_transition(TicketStatus.RESOLVED, TicketStatus.CLOSED)
    assert can_transition(TicketStatus.CLOSED, TicketStatus.OPEN)  # reopen
    # Illegal jumps are rejected.
    assert not can_transition(TicketStatus.OPEN, TicketStatus.CLOSED)
    assert not can_transition(TicketStatus.CLOSED, TicketStatus.RESOLVED)
