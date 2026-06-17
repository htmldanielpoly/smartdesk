"""Duplicate detection: OpenAI embeddings + cosine similarity, with a
token-overlap (Jaccard) fallback when embeddings are unavailable."""
import re

import numpy as np

from app.config import settings
from app.schemas import DuplicateCandidate, DuplicatesRequest, DuplicatesResponse
from app.services import openai_client

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0


def _rank(scored: list[tuple[str, str, float]], source: str, threshold: float) -> DuplicatesResponse:
    keep = [
        DuplicateCandidate(ticket_id=tid, title=title, similarity=round(score, 3))
        for tid, title, score in scored
        if score >= threshold
    ]
    keep.sort(key=lambda c: c.similarity, reverse=True)
    return DuplicatesResponse(candidates=keep[: settings.duplicate_max_results], source=source)


def find(req: DuplicatesRequest) -> DuplicatesResponse:
    if not req.candidates:
        return DuplicatesResponse(candidates=[], source="fallback")

    query_text = f"{req.title}. {req.description}"
    cand_texts = [f"{c.title}. {c.description}" for c in req.candidates]

    embeddings = openai_client.embed([query_text, *cand_texts])
    if embeddings is not None:
        q = np.array(embeddings[0])
        scored = [
            (c.ticket_id, c.title, _cosine(q, np.array(emb)))
            for c, emb in zip(req.candidates, embeddings[1:])
        ]
        return _rank(scored, "ai", settings.duplicate_similarity_threshold)

    # Fallback: lexical token overlap.
    q_tokens = _tokens(query_text)
    scored = [
        (c.ticket_id, c.title, _jaccard(q_tokens, _tokens(text)))
        for c, text in zip(req.candidates, cand_texts)
    ]
    return _rank(scored, "fallback", settings.duplicate_fallback_threshold)
