"""Tests for the local-LLM paths (mocked model) and KB grounding.

The real model never runs in unit tests; we monkeypatch llm_local to verify
the orchestration around it: schema-constrained classification, KB
retrieve-or-refuse, citation validation, and duplicate ranking.
"""
import pytest

from app.schemas import ClassifyRequest, CopilotRequest, DuplicateInput, DuplicatesRequest
from app.services import classifier, copilot, duplicates, kb, llm_local


@pytest.fixture(autouse=True)
def _fresh_kb_cache():
    kb.reset_cache()
    yield
    kb.reset_cache()


# --- classifier -----------------------------------------------------------

def test_classify_uses_local_model_and_derives_department(monkeypatch):
    monkeypatch.setattr(
        llm_local, "chat_json",
        lambda system, user, schema: {"category": "Network", "priority": "HIGH"},
    )
    res = classifier.classify(ClassifyRequest(title="VPN down", description="cannot connect"))
    assert res.source == "local"
    assert res.category == "Network"
    assert res.department == "Infrastructure"  # derived server-side, not by the model


def test_classify_falls_back_when_model_returns_garbage(monkeypatch):
    monkeypatch.setattr(
        llm_local, "chat_json",
        lambda system, user, schema: {"category": "NotACategory", "priority": "SUPER"},
    )
    res = classifier.classify(ClassifyRequest(title="hello", description="world"))
    # Whitelist validation catches labels outside the enum.
    assert res.category == "Other"
    assert res.priority == "MEDIUM"


def test_classify_falls_back_when_model_unavailable(monkeypatch):
    monkeypatch.setattr(llm_local, "chat_json", lambda *a, **kw: None)
    res = classifier.classify(ClassifyRequest(title="refund", description="billing issue"))
    assert res.source == "fallback"
    assert res.category == "Billing"


# --- knowledge base -------------------------------------------------------

def test_kb_lexical_retrieval_finds_relevant_article(monkeypatch):
    monkeypatch.setattr(llm_local, "embed", lambda texts: None)  # no embedding model
    results = kb.retrieve("I want a refund for my last invoice charge")
    assert results, "expected at least one KB hit"
    top_ids = [a["id"] for a, _ in results]
    assert any(i.startswith("KB-BIL") for i in top_ids)


def test_kb_returns_nothing_for_out_of_scope_query(monkeypatch):
    monkeypatch.setattr(llm_local, "embed", lambda texts: None)
    results = kb.retrieve("qwerty zxcvb asdfgh unrelated gibberish")
    assert results == []


# --- copilot (ground-or-refuse) -------------------------------------------

_ARTICLE = {
    "id": "KB-NET-001",
    "category": "Network",
    "title": "VPN will not connect",
    "body": "Switch the client to TCP mode.",
}


def test_copilot_refuses_without_kb_match(monkeypatch):
    monkeypatch.setattr(kb, "retrieve", lambda query: [])

    def _boom(*args, **kwargs):
        raise AssertionError("LLM must not generate without KB grounding")

    monkeypatch.setattr(llm_local, "chat_json", _boom)
    res = copilot.assist(CopilotRequest(title="teleporter broken", description="beam me up"))
    assert res.source == "fallback"
    assert "no_kb_match" in res.flags
    assert res.citations == []


def test_copilot_returns_grounded_answer_with_valid_citations(monkeypatch):
    monkeypatch.setattr(kb, "retrieve", lambda query: [(_ARTICLE, 0.82)])
    monkeypatch.setattr(
        llm_local, "chat_json",
        lambda system, user, schema: {
            "suggested_solution": "Per KB-NET-001, switch the VPN client to TCP mode.",
            "draft_response": "Hi, please switch your VPN client to TCP mode and retry.",
            "citations": ["KB-NET-001"],
        },
    )
    res = copilot.assist(
        CopilotRequest(title="VPN not connecting", description="fails since today")
    )
    assert res.source == "local"
    assert res.citations == ["KB-NET-001"]


def test_copilot_rejects_answer_with_fabricated_citation(monkeypatch):
    monkeypatch.setattr(kb, "retrieve", lambda query: [(_ARTICLE, 0.82)])
    monkeypatch.setattr(
        llm_local, "chat_json",
        lambda system, user, schema: {
            "suggested_solution": "Do something.",
            "draft_response": "Hi.",
            "citations": ["KB-DOES-NOT-EXIST"],
        },
    )
    res = copilot.assist(CopilotRequest(title="VPN not connecting", description="fails"))
    assert res.source == "fallback"
    assert "output_rejected" in res.flags


# --- duplicates ------------------------------------------------------------

def test_duplicates_use_local_embeddings_when_available(monkeypatch):
    # Query identical to candidate 1, orthogonal to candidate 2.
    vectors = {"q": [1.0, 0.0], "same": [1.0, 0.0], "other": [0.0, 1.0]}

    def fake_embed(texts):
        out = []
        for t in texts:
            if "printer" in t.lower():
                out.append(vectors["other"])
            else:
                out.append(vectors["same"])
        return out

    monkeypatch.setattr(llm_local, "embed", fake_embed)
    res = duplicates.find(
        DuplicatesRequest(
            title="VPN not connecting",
            description="fails",
            candidates=[
                DuplicateInput(ticket_id="1", title="VPN issue", description="fails too"),
                DuplicateInput(ticket_id="2", title="Printer jam", description="paper stuck"),
            ],
        )
    )
    assert res.source == "local"
    ids = [c.ticket_id for c in res.candidates]
    assert ids == ["1"]
