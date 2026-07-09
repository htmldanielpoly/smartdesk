"""Tests for incident clustering — the local-embedding path (mocked model)
and the lexical fallback. The real model never runs in unit tests."""
from app.schemas import ClusterItem, ClusterRequest
from app.services import clustering, llm_local


def _items():
    return [
        ClusterItem(id="1", title="Power outage Westbrook",
                    description="no electricity downtown blackout"),
        ClusterItem(id="2", title="Blackout Westbrook", description="whole street dark, no power"),
        ClusterItem(id="3", title="Total outage Westbrook", description="downtown has zero power"),
        ClusterItem(id="4", title="Brownout Riverton",
                    description="lights flickering after the storm"),
        ClusterItem(id="5", title="Flickering Riverton", description="voltage sag since the storm"),
        ClusterItem(id="6", title="Riverton storm",
                    description="a line is down, lights flickering"),
        ClusterItem(id="7", title="Billing question",
                    description="my monthly invoice is too high"),
    ]


def _groups_as_sets(res):
    return [set(g) for g in res.groups]


def test_cluster_uses_local_embeddings(monkeypatch):
    # Fake embeddings: three orthogonal directions -> three clean clusters.
    def fake_embed(texts):
        out = []
        for t in texts:
            tl = t.lower()
            if "westbrook" in tl:
                out.append([1.0, 0.0, 0.0])
            elif "riverton" in tl:
                out.append([0.0, 1.0, 0.0])
            else:
                out.append([0.0, 0.0, 1.0])
        return out

    monkeypatch.setattr(llm_local, "embed", fake_embed)
    res = clustering.cluster(ClusterRequest(items=_items()))

    assert res.source == "local"
    groups = _groups_as_sets(res)
    assert {"1", "2", "3"} in groups   # Westbrook incident
    assert {"4", "5", "6"} in groups   # Riverton incident
    assert {"7"} in groups             # billing is its own (noise) singleton


def test_cluster_falls_back_to_lexical(monkeypatch):
    monkeypatch.setattr(llm_local, "embed", lambda texts: None)
    res = clustering.cluster(ClusterRequest(items=_items()))

    assert res.source == "fallback"
    groups = _groups_as_sets(res)
    westbrook = next(g for g in groups if "1" in g)
    riverton = next(g for g in groups if "4" in g)
    assert {"1", "2", "3"} <= westbrook
    assert {"4", "5", "6"} <= riverton
    # The unrelated billing ticket must not be pulled into a power incident.
    assert "7" not in westbrook and "7" not in riverton


def test_cluster_empty_input():
    res = clustering.cluster(ClusterRequest(items=[]))
    assert res.groups == []
