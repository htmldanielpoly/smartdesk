"""Incident clustering: group related tickets into incidents.

Same engine as duplicate detection, applied to a whole batch: embed every
ticket with the local model and group by cosine similarity (single-linkage
agglomerative). When the embedding model is unavailable it falls back to
token-overlap (Jaccard), so an incident overview is always produced — just
lexically instead of semantically.

Returns groups of item ids; the caller (api-service) turns groups into the
manager rollup (severity, affected estimate, etc.).
"""
from collections.abc import Callable

import numpy as np

from app.config import settings
from app.schemas import ClusterRequest, ClusterResponse
from app.services import llm_local
from app.services.duplicates import _cosine, _jaccard, _tokens


def _single_linkage(n: int, sim: Callable[[int, int], float], threshold: float) -> list[list[int]]:
    """Greedy single-linkage: put each item in the existing cluster it is most
    similar to (best member similarity >= threshold), else start a new one."""
    clusters: list[list[int]] = []
    for i in range(n):
        best: list[int] | None = None
        best_score = threshold
        for cluster in clusters:
            score = max(sim(i, j) for j in cluster)
            if score >= best_score:
                best_score = score
                best = cluster
        if best is None:
            clusters.append([i])
        else:
            best.append(i)
    return clusters


def cluster(req: ClusterRequest) -> ClusterResponse:
    items = req.items
    if not items:
        return ClusterResponse(groups=[], source="fallback")

    ids = [it.id for it in items]
    texts = [f"{it.title}. {it.description}" for it in items]

    embeddings = llm_local.embed(texts)
    if embeddings is not None:
        vecs = [np.asarray(e, dtype=np.float32) for e in embeddings]
        groups = _single_linkage(
            len(items),
            lambda i, j: _cosine(vecs[i], vecs[j]),
            settings.cluster_similarity_threshold,
        )
        return ClusterResponse(groups=[[ids[i] for i in g] for g in groups], source="local")

    # Lexical fallback: token-overlap (Jaccard), no model needed.
    toks = [_tokens(t) for t in texts]
    groups = _single_linkage(
        len(items),
        lambda i, j: _jaccard(toks[i], toks[j]),
        settings.cluster_fallback_threshold,
    )
    return ClusterResponse(groups=[[ids[i] for i in g] for g in groups], source="fallback")
