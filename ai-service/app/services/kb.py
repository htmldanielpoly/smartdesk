"""Knowledge-base retrieval for grounded (hallucination-free) copilot answers.

The copilot is only allowed to answer from these curated articles. Retrieval
uses the local embedding model when it is ready and falls back to lexical
token overlap otherwise. When nothing in the KB is similar enough to the
ticket, the copilot refuses to generate — a template answer is returned
instead of letting the model invent policy.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.config import settings
from app.services import llm_local

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "kb_articles.json"

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Minimal stopword list so lexical matching keys on content words.
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "for",
    "from", "get", "has", "have", "how", "i", "in", "is", "it", "its", "me",
    "my", "no", "not", "of", "on", "or", "our", "so", "that", "the", "their",
    "this", "to", "want", "was", "we", "when", "will", "with", "you", "your",
}

# Cache of article embeddings, computed once after the model becomes ready.
_embeddings: list[np.ndarray] | None = None


@lru_cache(maxsize=1)
def articles() -> list[dict]:
    with open(_DATA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def article_ids() -> set[str]:
    return {a["id"] for a in articles()}


def _article_text(article: dict) -> str:
    return f"{article['title']}. {article['body']}"


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower())) - _STOPWORDS


def _coverage(query: set[str], doc: set[str]) -> float:
    """Fraction of query content-words found in the document. Better suited
    than Jaccard for a short query against a long article (where the union
    term would drown the score)."""
    if not query or not doc:
        return 0.0
    return len(query & doc) / len(query)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0


def _ensure_embeddings() -> bool:
    global _embeddings
    if _embeddings is not None:
        return True
    vectors = llm_local.embed([_article_text(a) for a in articles()])
    if vectors is None:
        return False
    _embeddings = [np.asarray(v, dtype=np.float32) for v in vectors]
    return True


def reset_cache() -> None:
    """Drop cached embeddings (used by tests)."""
    global _embeddings
    _embeddings = None


def retrieve(query: str) -> list[tuple[dict, float]]:
    """Top-k KB articles relevant to ``query`` with their similarity, best
    first. Only articles above the (path-specific) threshold are returned;
    an empty list means "the KB cannot answer this"."""
    if _ensure_embeddings():
        query_vec = llm_local.embed([query])
        if query_vec is not None:
            q = np.asarray(query_vec[0], dtype=np.float32)
            scored = [
                (article, _cosine(q, emb))
                for article, emb in zip(articles(), _embeddings, strict=False)
            ]
            threshold = settings.kb_min_similarity
        else:
            scored, threshold = _lexical_scores(query)
    else:
        scored, threshold = _lexical_scores(query)

    scored = [(a, s) for a, s in scored if s >= threshold]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[: settings.kb_top_k]


def _lexical_scores(query: str) -> tuple[list[tuple[dict, float]], float]:
    q_tokens = _tokens(query)
    scored = [
        (article, _coverage(q_tokens, _tokens(_article_text(article))))
        for article in articles()
    ]
    return scored, settings.kb_lexical_min_similarity
