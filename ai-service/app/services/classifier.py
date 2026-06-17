"""Ticket classification: OpenAI when available, keyword rules otherwise."""
import json

from app.schemas import ClassifyRequest, ClassifyResponse
from app.services import openai_client

CATEGORIES = ["Account", "Billing", "Technical", "Network", "Hardware", "Other"]
PRIORITIES = ["LOW", "MEDIUM", "HIGH", "URGENT"]

# Keyword heuristics for the offline fallback.
_CATEGORY_KEYWORDS = {
    "Account": ["login", "password", "sign in", "account", "register", "2fa"],
    "Billing": ["invoice", "payment", "charge", "refund", "billing", "subscription"],
    "Network": ["network", "vpn", "wifi", "connection", "internet", "dns"],
    "Hardware": ["printer", "laptop", "monitor", "keyboard", "device", "screen"],
    "Technical": ["error", "bug", "crash", "500", "exception", "fails", "broken"],
}
_DEPARTMENT_BY_CATEGORY = {
    "Account": "Identity",
    "Billing": "Finance",
    "Network": "Infrastructure",
    "Hardware": "IT Support",
    "Technical": "Engineering",
    "Other": "General Support",
}
_URGENT_WORDS = ["urgent", "asap", "immediately", "critical", "outage", "down"]
_HIGH_WORDS = ["cannot", "can't", "blocked", "error", "broken", "fails"]


def _fallback(req: ClassifyRequest) -> ClassifyResponse:
    text = f"{req.title} {req.description}".lower()

    category = "Other"
    for cat, words in _CATEGORY_KEYWORDS.items():
        if any(w in text for w in words):
            category = cat
            break

    if any(w in text for w in _URGENT_WORDS):
        priority = "URGENT"
    elif any(w in text for w in _HIGH_WORDS):
        priority = "HIGH"
    else:
        priority = "MEDIUM"

    return ClassifyResponse(
        category=category,
        priority=priority,
        department=_DEPARTMENT_BY_CATEGORY[category],
        confidence=0.5,
        source="fallback",
    )


def classify(req: ClassifyRequest) -> ClassifyResponse:
    system = (
        "You classify IT support tickets. Respond ONLY with JSON: "
        '{"category": one of ' + str(CATEGORIES) + ', "priority": one of '
        + str(PRIORITIES) + ', "department": string}.'
    )
    raw = openai_client.chat(system, f"Title: {req.title}\nDescription: {req.description}")
    if raw is None:
        return _fallback(req)
    try:
        data = json.loads(raw)
        return ClassifyResponse(
            category=data["category"],
            priority=data["priority"],
            department=data["department"],
            confidence=0.9,
            source="ai",
        )
    except (json.JSONDecodeError, KeyError):
        return _fallback(req)
