"""Tests for the rule-based fallbacks (run with no OpenAI key)."""
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import ClassifyRequest, DuplicateInput, DuplicatesRequest
from app.services import classifier, duplicates

client = TestClient(app)


def test_classify_fallback_detects_account_and_urgency():
    res = classifier.classify(
        ClassifyRequest(title="Cannot login", description="URGENT: password reset fails")
    )
    assert res.source == "fallback"
    assert res.category == "Account"
    assert res.priority == "URGENT"
    assert res.department == "Identity"


def test_duplicates_fallback_ranks_similar_tickets():
    req = DuplicatesRequest(
        title="VPN not connecting",
        description="The corporate VPN client fails to connect since this morning",
        candidates=[
            DuplicateInput(
                ticket_id="1",
                title="VPN connection problem",
                description="corporate VPN client will not connect this morning",
            ),
            DuplicateInput(
                ticket_id="2",
                title="Printer jam",
                description="the office printer keeps jamming on page 2",
            ),
        ],
    )
    res = duplicates.find(req)
    ids = [c.ticket_id for c in res.candidates]
    assert "1" in ids  # the VPN ticket is flagged
    assert "2" not in ids  # the printer ticket is not


def test_health_endpoint_reports_ai_disabled():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ai_enabled"] is False


def test_classify_endpoint_end_to_end():
    r = client.post(
        "/classify",
        json={"title": "Refund request", "description": "I want a refund for my invoice"},
    )
    assert r.status_code == 200
    assert r.json()["category"] == "Billing"
