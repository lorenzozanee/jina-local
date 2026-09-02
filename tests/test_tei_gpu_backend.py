import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "mcp-gateway" / "src"


def _load(name):
    path = SRC / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _tei_available(url):
    try:
        import requests
        response = requests.get(url.replace("/embed", "/health").replace("/rerank", "/health"), timeout=2)
        return response.status_code < 500
    except Exception:
        return False


@pytest.mark.skipif(not _tei_available("http://127.0.0.1:3001/embed"), reason="TEI embeddings service unavailable")
def test_embeddings_prefers_tei_backend():
    module = _load("embeddings")
    module._backend = None
    module._model = None
    module._model_ref = None
    result = module.embed(["GPU accelerated local retrieval"])
    assert len(result) == 1
    assert len(result[0]) > 0
    assert abs(sum(value * value for value in result[0]) ** 0.5 - 1) < 1e-3
    assert module.get_backend() == "tei"


@pytest.mark.skipif(not _tei_available("http://127.0.0.1:3002/rerank"), reason="TEI reranker service unavailable")
def test_reranker_prefers_tei_backend():
    module = _load("reranker")
    module._backend = None
    module._model = None
    module._model_ref = None
    result = module.rerank("apple fruit", ["Car engine", "Apple is a fruit"])
    assert result[0]["document"] == "Apple is a fruit"
    assert 0 <= result[0]["relevance_score"] <= 1
    assert module.get_backend() == "tei"


@pytest.mark.skipif(not _tei_available("http://127.0.0.1:3001/embed"), reason="TEI embeddings service unavailable")
def test_gateway_uses_tei_for_embeddings():
    module = _load("gateway")
    result = module.embed(["TEI backend verification"])
    assert result
    assert module.get_embedding_backend() == "tei"


@pytest.mark.skipif(not _tei_available("http://127.0.0.1:3002/rerank"), reason="TEI reranker service unavailable")
def test_gateway_uses_tei_for_reranking():
    module = _load("gateway")
    result = module.rerank("GPU inference", ["CPU only", "GPU inference service"])
    assert result[0]["document"] == "GPU inference service"
    assert module.get_reranker_backend() == "tei"


def test_tei_endpoints_are_configurable(monkeypatch):
    module = _load("embeddings")
    monkeypatch.setenv("JINA_LOCAL_EMBEDDINGS_URL", "http://127.0.0.1:39991/embed")
    assert module._tei_url() == "http://127.0.0.1:39991/embed"
    module = _load("reranker")
    monkeypatch.setenv("JINA_LOCAL_RERANKER_URL", "http://127.0.0.1:39992/rerank")
    assert module._tei_url() == "http://127.0.0.1:39992/rerank"
