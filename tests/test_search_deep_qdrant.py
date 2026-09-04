import importlib
import sys



def test_search_deep_qdrant_enrichment_is_optional(monkeypatch):
    deep = importlib.import_module("search_deep")
    qdrant = importlib.import_module("qdrant")
    calls = []

    monkeypatch.setenv("JINA_LOCAL_ENABLE_QDRANT", "1")
    monkeypatch.setattr(qdrant, "enrich_search_results", lambda results, vector, limit=5: calls.append((results, vector, limit)) or results)
    monkeypatch.setattr(deep, "_get_search_fn", lambda explicit: lambda query, num=5: [{"title": "A", "url": "https://a", "content": "snippet", "source": "test", "retrieved_at": "2026-09-04T00:00:00Z"}])
    monkeypatch.setattr(deep, "_get_reader_fn", lambda explicit: lambda urls: ["content about gpu"])
    monkeypatch.setattr(deep, "_get_reranker_fn", lambda explicit: lambda query, chunks: [{"document": chunks[0], "relevance_score": 0.9}])
    monkeypatch.setattr(deep, "_read_cache", lambda *args: None)
    monkeypatch.setattr(deep, "_write_cache", lambda *args: None)
    monkeypatch.setattr(deep, "_get_query_embedding", lambda query: [0.1, 0.2])

    result = deep.search_web_deep("gpu", num=1, chunk_size=20)
    assert result[0]["url"] == "https://a"
    assert calls and calls[0][1] == [0.1, 0.2]
