import importlib

import httpx


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("failure", request=None, response=None)

    def json(self):
        return self.payload


def module():
    return importlib.import_module("qdrant")


def test_search_returns_payload(monkeypatch):
    q = module()
    calls = []
    monkeypatch.setattr(q.httpx, "post", lambda url, **kw: (calls.append((url, kw)) or FakeResponse(payload={"result": [{"id": "a", "score": .9}]})))
    assert q.search([.1, .2], limit=3) == [{"id": "a", "score": .9}]
    assert calls[0][1]["json"]["limit"] == 3
    assert calls[0][1]["trust_env"] is False


def test_search_unavailable_returns_none(monkeypatch):
    q = module()
    monkeypatch.setattr(q.httpx, "post", lambda *a, **kw: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    assert q.search([.1]) is None


def test_upsert_returns_success(monkeypatch):
    q = module()
    calls = []
    monkeypatch.setattr(q.httpx, "put", lambda url, **kw: (calls.append((url, kw)) or FakeResponse()))
    assert q.upsert([{"id": 1, "vector": [.1], "payload": {"text": "one"}}]) is True
    assert calls[0][1]["trust_env"] is False


def test_health_ignores_system_proxy(monkeypatch):
    q = module()
    calls = []
    monkeypatch.setattr(q.httpx, "get", lambda url, **kw: (calls.append(kw) or FakeResponse()))
    assert q.health() is True
    assert calls[0]["trust_env"] is False


def test_merge_results_prefers_combined_scores():
    q = module()
    merged = q.merge_results([{"id": "a", "score": .9}, {"id": "b", "score": .8}], [{"id": "b", "score": .99}, {"id": "c", "score": .95}], limit=3)
    assert [item["id"] for item in merged] == ["b", "c", "a"]


def test_merge_results_normalizes_negative_cosine_scores():
    q = module()
    merged = q.merge_results([{"id": "lexical", "score": .2}], [{"id": "relevant", "score": -.01}, {"id": "unrelated", "score": -.4}], limit=3)
    assert [item["id"] for item in merged][:2] == ["relevant", "unrelated"]


def test_normalize_results_requires_search_contract():
    q = module()
    assert q.normalize_results([{"score": .9, "payload": {"title": "A", "url": "https://a", "content": "body"}}, {"score": .8, "payload": {"content": "invalid"}}]) == [{"title": "A", "url": "https://a", "content": "body", "score": .9}]


def test_merge_results_deduplicates_standard_urls():
    q = module()
    merged = q.merge_results([{"title": "A", "url": "https://a", "content": "lexical", "score": .8}], [{"title": "A", "url": "https://a", "content": "vector", "score": 1.0}], limit=5)
    assert len(merged) == 1


def test_merge_results_keeps_normalized_vector_scores():
    q = module()
    merged = q.merge_results([{"title": "A", "url": "https://a", "score": .2}], [{"title": "B", "url": "https://b", "score": 1.0}], limit=2)
    assert merged[0]["url"] == "https://b"
    assert merged[0]["hybrid_score"] == .5


def test_enrich_keeps_lexical_when_vector_unavailable(monkeypatch):
    q = module()
    lexical = [{"title": "A", "url": "https://a", "score": .4}]
    monkeypatch.setattr(q, "search", lambda vector, limit=5: None)
    assert q.enrich_search_results(lexical, [.1, .2]) == lexical
