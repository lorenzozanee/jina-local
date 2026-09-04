import importlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = str(ROOT / "mcp-gateway" / "src")
if SOURCE_PATH not in sys.path:
    sys.path.insert(0, SOURCE_PATH)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def load_module(monkeypatch):
    for name in (
        "JINA_LOCAL_LLM_BASE_URL",
        "JINA_LOCAL_LLM_MODEL",
        "JINA_LOCAL_LLM_API_KEY",
        "JINA_LOCAL_LLM_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    sys.modules.pop("search_llm", None)
    return importlib.import_module("search_llm")


def test_missing_configuration_is_disabled_and_safe(monkeypatch):
    module = load_module(monkeypatch)

    assert module.is_enabled() is False
    assert module.plan_queries("complex retrieval question") == []
    assert module.rerank_ids("q", [{"id": "a"}]) is None


def test_query_planning_uses_bounded_openai_json_schema_request(monkeypatch):
    module = load_module(monkeypatch)
    monkeypatch.setenv("JINA_LOCAL_LLM_BASE_URL", "https://llm.example/v1///")
    monkeypatch.setenv("JINA_LOCAL_LLM_MODEL", "search-model")
    monkeypatch.setenv("JINA_LOCAL_LLM_API_KEY", "test-only-key")
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"queries": ["alpha", "", "alpha", " beta "]}
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(module.requests, "post", fake_post)

    assert module.is_enabled() is True
    assert module.plan_queries("complex retrieval question") == ["alpha", "beta"]
    url, kwargs = calls[0]
    assert url == "https://llm.example/v1/chat/completions"
    assert kwargs["headers"] == {
        "Authorization": "Bearer test-only-key",
        "Content-Type": "application/json",
    }
    assert kwargs["timeout"] > 0
    body = kwargs["json"]
    assert body["model"] == "search-model"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"]["required"] == ["queries"]


def test_reranking_rejects_unknown_and_duplicate_ids(monkeypatch):
    module = load_module(monkeypatch)
    monkeypatch.setenv("JINA_LOCAL_LLM_BASE_URL", "https://llm.example")
    monkeypatch.setenv("JINA_LOCAL_LLM_MODEL", "search-model")
    monkeypatch.setenv("JINA_LOCAL_LLM_API_KEY", "test-only-key")
    candidates = [
        {"id": "a", "title": "A", "url": "https://a.example", "content": "a"},
        {"id": "b", "title": "B", "url": "https://b.example", "content": "b"},
    ]
    responses = iter(
        [
            FakeResponse({"choices": [{"message": {"content": '{"ids":["a","x"]}'}}]}),
            FakeResponse({"choices": [{"message": {"content": '{"ids":["a","a"]}'}}]}),
        ]
    )
    monkeypatch.setattr(module.requests, "post", lambda *args, **kwargs: next(responses))

    assert module.rerank_ids("q", candidates) is None
    assert module.rerank_ids("q", candidates) is None


def test_reranking_returns_only_a_complete_candidate_permutation(monkeypatch):
    module = load_module(monkeypatch)
    monkeypatch.setenv("JINA_LOCAL_LLM_BASE_URL", "https://llm.example/")
    monkeypatch.setenv("JINA_LOCAL_LLM_MODEL", "search-model")
    monkeypatch.setenv("JINA_LOCAL_LLM_API_KEY", "test-only-key")
    candidates = [
        {"id": "a", "title": "A", "url": "https://a.example", "content": "a", "source": "x"},
        {"id": "b", "title": "B", "url": "https://b.example", "content": "b", "source": "y"},
    ]
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return FakeResponse({"choices": [{"message": {"content": '{"ids":["b","a"]}'}}]})

    monkeypatch.setattr(module.requests, "post", fake_post)

    assert module.rerank_ids("q", candidates) == ["b", "a"]
    sent = captured["json"]["messages"]
    assert "source" not in json.dumps(sent)
    assert "https://a.example" in json.dumps(sent)
