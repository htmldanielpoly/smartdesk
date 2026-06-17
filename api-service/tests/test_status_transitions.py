"""Unit tests for the ticket status machine. No DB or network required."""
import pytest

from app.models.enums import TicketStatus, can_transition


@pytest.mark.parametrize(
    "current,target",
    [
        (TicketStatus.OPEN, TicketStatus.IN_PROGRESS),
        (TicketStatus.OPEN, TicketStatus.RESOLVED),
        (TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED),
        (TicketStatus.RESOLVED, TicketStatus.CLOSED),
        (TicketStatus.CLOSED, TicketStatus.OPEN),  # reopen
    ],
)
def test_allowed_transitions(current, target):
    assert can_transition(current, target) is True


@pytest.mark.parametrize(
    "current,target",
    [
        (TicketStatus.OPEN, TicketStatus.CLOSED),
        (TicketStatus.CLOSED, TicketStatus.RESOLVED),
        (TicketStatus.RESOLVED, TicketStatus.OPEN),
    ],
)
def test_forbidden_transitions(current, target):
    assert can_transition(current, target) is False


def test_self_transition_is_noop_allowed():
    assert can_transition(TicketStatus.OPEN, TicketStatus.OPEN) is True
