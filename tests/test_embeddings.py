"""Embeddings 本地替代测试 - TDD
要求 6 测：
- test_embeddings_returns_vector
- test_embeddings_normalized
- test_embeddings_semantic_similarity
- test_embeddings_batch
- test_embeddings_empty_error
- test_embeddings_dimension
"""
import importlib.util
import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATES = [
    ROOT / "mcp-gateway" / "src" / "embeddings.py",
    ROOT / "mcp-gateway" / "src" / "gateway.py",
    ROOT / "mcp-gateway" / "src" / "server.py",
]


def _resolve():
    for p in CANDIDATES:
        if p.exists():
            return p
    return None


def _load():
    path = _resolve()
    assert path is not None, f"功能缺失: Embeddings 模块不存在 {CANDIDATES}"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod, path


def _get_embed_callable():
    mod, _ = _load()
    # support embed, embeddings, embed_texts
    for name in ("embed", "embeddings", "embed_texts", "encode"):
        if hasattr(mod, name) and callable(getattr(mod, name)):
            return getattr(mod, name), mod
    pytest.fail(f"功能缺失: 未暴露 embed/embeddings 入口, 已检查 {CANDIDATES}")


def _get_embed_one():
    mod, _ = _load()
    for name in ("embed_one", "embed_single", "encode_one"):
        if hasattr(mod, name) and callable(getattr(mod, name)):
            return getattr(mod, name), mod
    # fallback: use embed wrapper if no embed_one
    embed_fn, _ = _get_embed_callable()
    return None, mod


def _cosine(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    # vectors assumed normalized if impl correct, but compute explicit
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(y*y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def test_embeddings_returns_vector():
    """对文本返回定长向量"""
    embed_fn, mod = _get_embed_callable()
    vectors = embed_fn(["hello world"])
    assert isinstance(vectors, list), "embed 应返回 list[list[float]]"
    assert len(vectors) == 1
    vec = vectors[0]
    assert isinstance(vec, list), "向量应为 list[float]"
    assert len(vec) > 0, "向量长度应 >0"
    for v in vec:
        assert isinstance(v, (int, float)), "向量元素应为 float"


def test_embeddings_normalized():
    """余弦相似度可用，L2 范数为1"""
    embed_fn, mod = _get_embed_callable()
    vectors = embed_fn(["hello world"])
    vec = vectors[0]
    norm = math.sqrt(sum(x*x for x in vec))
    assert abs(norm - 1.0) < 1e-3, f"L2范数应为1，实际 {norm}"
    # cosine self =1
    sim = _cosine(vec, vec)
    assert abs(sim - 1.0) < 1e-3, f"自身余弦应为1，实际 {sim}"


def test_embeddings_semantic_similarity():
    """apple fruit 与 Apple is a fruit 相似度 > apple fruit 与 car engine"""
    embed_fn, _ = _get_embed_callable()
    texts = ["apple fruit", "Apple is a fruit", "car engine"]
    vecs = embed_fn(texts)
    assert len(vecs) == 3
    sim_pos = _cosine(vecs[0], vecs[1])
    sim_neg = _cosine(vecs[0], vecs[2])
    assert sim_pos > sim_neg, f"语义区分度不足: pos {sim_pos:.4f} <= neg {sim_neg:.4f}"
    # also require meaningful gap
    assert sim_pos - sim_neg > 0.05, f"语义区分度差值过小: pos {sim_pos:.4f} neg {sim_neg:.4f} diff {sim_pos-sim_neg:.4f}"


def test_embeddings_batch():
    """批量文本"""
    embed_fn, _ = _get_embed_callable()
    texts = ["hello", "world", "hello world", "test case"]
    vecs = embed_fn(texts)
    assert isinstance(vecs, list) and len(vecs) == len(texts)
    dim = len(vecs[0])
    for v in vecs:
        assert len(v) == dim, "批量维度应一致"
        n = math.sqrt(sum(x*x for x in v))
        assert abs(n - 1.0) < 1e-3


def test_embeddings_empty_error():
    """严格校验空输入"""
    embed_fn, mod = _get_embed_callable()
    # empty list
    with pytest.raises((ValueError, TypeError)):
        embed_fn([])
    # list with empty string
    with pytest.raises((ValueError, TypeError)):
        embed_fn([""])
    with pytest.raises((ValueError, TypeError)):
        embed_fn(["   "])
    # None input
    with pytest.raises((ValueError, TypeError)):
        embed_fn(None)  # type: ignore
    # embed_one if exists should also raise
    embed_one_fn, _ = _get_embed_one()
    if embed_one_fn is not None:
        with pytest.raises((ValueError, TypeError)):
            embed_one_fn("")
        with pytest.raises((ValueError, TypeError)):
            embed_one_fn("   ")
        with pytest.raises((ValueError, TypeError)):
            embed_one_fn(None)  # type: ignore


def test_embeddings_dimension():
    """默认维度 1024 或 384 等一致"""
    embed_fn, mod = _get_embed_callable()
    vecs = embed_fn(["test dimension"])
    dim = len(vecs[0])
    # allow 384 (MiniLM), 768, 1024 (bge-m3), 512, 256 etc but must be consistent
    assert dim in (384, 768, 1024, 512, 256, 128, 1536), f"维度 {dim} 不在预期集合 {{384,768,1024,512,256}}，需一致"
    # second call same dim
    vecs2 = embed_fn(["another text", "yet another"])
    for v in vecs2:
        assert len(v) == dim, f"维度不一致：期望 {dim}，实际 {len(v)}"
    # embed_one dimension matches
    embed_one_fn, _ = _get_embed_one()
    if embed_one_fn is not None:
        v1 = embed_one_fn("hello single")
        assert len(v1) == dim
