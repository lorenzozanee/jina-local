"""Reranker 本地替代测试 - sort_by_relevance

给定 query + documents 返回按相关性排序的 documents 及分数
TDD 红阶段：全部 FAIL，原因为功能缺失
"""
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATES = [
    ROOT / "mcp-gateway" / "src" / "reranker.py",
    ROOT / "mcp-gateway" / "src" / "gateway.py",
    ROOT / "mcp-gateway" / "src" / "server.py",
]


def _resolve_reranker_path():
    for p in CANDIDATES:
        if p.exists():
            return p
    return None


def _load_module(path: pathlib.Path):
    assert path is not None, f"功能缺失: Reranker 模块不存在 {path}"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader, f"功能缺失: 无法加载 {path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def _get_reranker_callable():
    path = _resolve_reranker_path()
    assert path is not None, f"功能缺失: Reranker 实现不存在，检查 {CANDIDATES}"
    mod = _load_module(path)
    for name in ("sort_by_relevance", "rerank", "reranker"):
        if hasattr(mod, name) and callable(getattr(mod, name)):
            return getattr(mod, name)
    pytest.fail(f"功能缺失: {path} 未暴露 sort_by_relevance/rerank 入口")


SAMPLE_DOCS = [
    "Apple is a fruit that grows on trees",
    "Car engine contains pistons and cylinders",
    "Apple pie recipe with cinnamon and sugar",
    "Quantum physics describes entangled particles",
]


def test_reranker_returns_list_for_query_and_documents():
    """给定 query+documents 应返回列表"""
    fn = _get_reranker_callable()
    results = fn(query="apple fruit", documents=SAMPLE_DOCS)
    assert isinstance(results, list), "功能缺失: sort_by_relevance 应返回 list"
    assert len(results) == len(SAMPLE_DOCS), "功能缺失: 返回数量应与输入 documents 等长"


def test_reranker_result_items_have_document_and_score():
    """返回项需包含 document/text 与分数（relevance_score/score）"""
    fn = _get_reranker_callable()
    results = fn(query="apple", documents=SAMPLE_DOCS)
    assert len(results) > 0
    first = results[0]
    assert isinstance(first, dict), "功能缺失: reranker 结果项应为 dict"
    # document 字段兼容 document/text/content
    doc_field = next((k for k in ("document", "text", "content") if k in first), None)
    assert doc_field is not None, f"功能缺失: 缺少 document/text 字段，实际 {list(first.keys())}"
    score_field = next((k for k in ("relevance_score", "score", "relevance") if k in first), None)
    assert score_field is not None, f"功能缺失: 缺少分数列 relevance_score/score，实际 {list(first.keys())}"
    assert isinstance(first[score_field], (int, float))


def test_reranker_sorted_by_relevance_descending():
    """返回结果应按相关性分数降序排列，且最相关文档靠前"""
    fn = _get_reranker_callable()
    results = fn(query="apple fruit", documents=SAMPLE_DOCS)
    assert isinstance(results, list) and len(results) >= 2
    # 提取分数
    def _score(item):
        for k in ("relevance_score", "score", "relevance"):
            if k in item:
                return float(item[k])
        return 0.0

    scores = [_score(r) for r in results]
    assert scores == sorted(scores, reverse=True), f"功能缺失: 未按相关性降序，scores={scores}"
    # 最相关的应是含 apple fruit 的文档
    top_doc = next((r.get("document") or r.get("text") or r.get("content") or "") for r in [results[0]])
    assert "Apple" in top_doc or "apple" in top_doc.lower(), "功能缺失: 排序结果顶部应为最相关文档"


def test_reranker_requires_query_param():
    """缺少 query 应抛 TypeError"""
    fn = _get_reranker_callable()
    with pytest.raises(TypeError):
        fn(documents=SAMPLE_DOCS)  # type: ignore[call-arg]


def test_reranker_requires_documents_param():
    """缺少 documents 应抛 TypeError"""
    fn = _get_reranker_callable()
    with pytest.raises(TypeError):
        fn(query="apple")  # type: ignore[call-arg]


def test_reranker_preserves_documents_content():
    """返回的 document 集合应与输入集合一致（仅重排，不丢失或篡改）"""
    fn = _get_reranker_callable()
    results = fn(query="quantum", documents=SAMPLE_DOCS)
    returned_docs = {
        (r.get("document") or r.get("text") or r.get("content") or "").strip()
        for r in results
    }
    expected = {d.strip() for d in SAMPLE_DOCS}
    assert returned_docs == expected, f"功能缺失: 返回文档集合不一致，期望 {expected}, 实际 {returned_docs}"
