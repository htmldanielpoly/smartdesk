"""Duplicate detection: local embeddings + cosine similarity, with a
token-overlap (Jaccard) fallback when the embedding model is unavailable.

``similarities`` is the shared scoring primitive: ``find`` ranks candidates
for the agent-facing duplicate finder, and ``memory.auto_resolve`` reuses the
same scores under a much stricter threshold."""
import re

import numpy as np

from app.config import settings
from app.schemas import DuplicateCandidate, DuplicatesRequest, DuplicatesResponse
from app.services import llm_local

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


def similarities(query_text: str, cand_texts: list[str]) -> tuple[list[float], str]:
    """Score ``query_text`` against every candidate text.

    Returns ``(scores, source)`` where ``source`` is ``"local"`` (cosine over
    local embeddings) or ``"fallback"`` (lexical Jaccard overlap). The two
    paths score on different scales, so callers pick their threshold
    according to ``source``.
    """
    if not cand_texts:
        return [], "fallback"

    embeddings = llm_local.embed([query_text, *cand_texts])
    if embeddings is not None:
        q = np.asarray(embeddings[0], dtype=np.float32)
        scores = [_cosine(q, np.asarray(emb, dtype=np.float32)) for emb in embeddings[1:]]
        return scores, "local"

    q_tokens = _tokens(query_text)
    return [_jaccard(q_tokens, _tokens(text)) for text in cand_texts], "fallback"


def _rank(
    scored: list[tuple[str, str, float]], source: str, threshold: float
) -> DuplicatesResponse:
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

    scores, source = similarities(query_text, cand_texts)
    scored = [
        (c.ticket_id, c.title, score)
        for c, score in zip(req.candidates, scores, strict=True)
    ]
    threshold = (
        settings.duplicate_similarity_threshold
        if source == "local"
        else settings.duplicate_fallback_threshold
    )
    return _rank(scored, source, threshold)
