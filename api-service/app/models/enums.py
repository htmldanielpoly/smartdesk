from enum import Enum


class Role(str, Enum):
    USER = "USER"
    AGENT = "AGENT"
    ADMIN = "ADMIN"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


# Allowed status transitions. Keys are current status, values the set of
# statuses reachable from it. This is the single source of truth for the
# ticket status machine and is unit-tested directly.
ALLOWED_TRANSITIONS: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.OPEN: {TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED},
    TicketStatus.IN_PROGRESS: {TicketStatus.OPEN, TicketStatus.RESOLVED},
    TicketStatus.RESOLVED: {TicketStatus.IN_PROGRESS, TicketStatus.CLOSED},
    TicketStatus.CLOSED: {TicketStatus.OPEN},  # reopen
}


def can_transition(current: TicketStatus, target: TicketStatus) -> bool:
    """Return True if a ticket may move from ``current`` to ``target``."""
    if current == target:
        return True
    return target in ALLOWED_TRANSITIONS.get(current, set())
