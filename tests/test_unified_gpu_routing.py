import importlib
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "mcp-gateway" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_utils_embeddings_use_gateway_facade(monkeypatch):
    gateway = importlib.import_module("gateway")
    utils = importlib.import_module("utils")
    calls = []

    def fake_embed(texts):
        calls.append(texts)
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(gateway, "embed", fake_embed)
    monkeypatch.setattr(utils, "_get_gateway", lambda: gateway)

    assert len(utils._get_embeddings(["one", "two"])) == 2
    assert calls == [["one", "two"]]


def test_server_exposes_embedding_tool():
    server = importlib.import_module("server")
    assert hasattr(server, "embeddings")
    assert callable(server.embeddings)


def test_fallback_exports_do_not_reference_missing_embedding_tool():
    server_path = ROOT / "mcp-gateway" / "src" / "server.py"
    source = server_path.read_text()
    fallback = source.split("else:  # fallback when mcp not installed", 1)[1]
    assert '"embeddings_tool"' not in fallback
    assert '"embeddings"' in fallback
