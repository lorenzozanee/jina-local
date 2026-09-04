"""Reader / Search 本地替代最小行为测试

Reader: 给定 URL 返回 markdown 文本
Search: 给定 query 返回搜索结果列表（含 title/url/content）
TDD 红阶段：仅测试，不实现，全部应 FAIL
"""
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATES = [
    ROOT / "mcp-gateway" / "src" / "gateway.py",
    ROOT / "mcp-gateway" / "src" / "server.py",
]
READER_CANDIDATES = [
    ROOT / "mcp-gateway" / "src" / "reader.py",
    ROOT / "mcp-gateway" / "src" / "gateway.py",
    ROOT / "mcp-gateway" / "src" / "server.py",
]
SEARCH_CANDIDATES = [
    ROOT / "mcp-gateway" / "src" / "search.py",
    ROOT / "mcp-gateway" / "src" / "gateway.py",
    ROOT / "mcp-gateway" / "src" / "server.py",
]


def _resolve_first(paths):
    for p in paths:
        if p.exists():
            return p
    return None


def _load_module(path: pathlib.Path):
    assert path is not None, f"功能缺失: 未找到模块文件 {path}"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader, f"功能缺失: 无法加载模块 {path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def _get_reader_callable():
    path = _resolve_first(READER_CANDIDATES)
    assert path is not None, f"功能缺失: Reader 实现不存在，检查 {READER_CANDIDATES}"
    mod = _load_module(path)
    # 兼容：模块暴露 read_url 或 reader  callable
    for name in ("read_url", "reader", "fetch"):
        if hasattr(mod, name) and callable(getattr(mod, name)):
            return getattr(mod, name)
    pytest.fail(f"功能缺失: {path} 未暴露 read_url/reader 可调用入口")


def _get_search_callable():
    path = _resolve_first(SEARCH_CANDIDATES)
    assert path is not None, f"功能缺失: Search 实现不存在，检查 {SEARCH_CANDIDATES}"
    mod = _load_module(path)
    for name in ("search_web", "search", "search_web_deep"):
        if hasattr(mod, name) and callable(getattr(mod, name)):
            return getattr(mod, name)
    pytest.fail(f"功能缺失: {path} 未暴露 search_web/search 可调用入口")


def _get_search_module():
    path = _resolve_first(SEARCH_CANDIDATES)
    assert path is not None, f"功能缺失: Search 实现不存在，检查 {SEARCH_CANDIDATES}"
    return _load_module(path)


def _retrieved_candidate(query: str) -> dict:
    return {
        "title": f"{query} documentation",
        "url": "https://example.com/docs",
        "content": f"Retrieved documentation about {query}.",
        "source": "searxng",
        "retrieved_at": "2026-09-04T00:00:00Z",
    }


def test_reader_returns_markdown_string_for_url():
    """Reader 给定 URL 应返回 markdown 字符串（非空）"""
    read_fn = _get_reader_callable()
    result = read_fn(url="https://example.com")
    assert isinstance(result, str), "功能缺失: read_url 应返回 str 类型的 markdown"
    assert len(result.strip()) > 0, "功能缺失: read_url 返回的 markdown 不应为空"


def test_reader_output_contains_markdown_or_text_content():
    """Reader 返回内容应包含可读正文（markdown 标题或 Example Domain 文本）"""
    read_fn = _get_reader_callable()
    result = read_fn(url="https://example.com")
    assert isinstance(result, str)
    # 真实站点 example.com 的本地抽取应包含 Example Domain 或 markdown 标题
    assert "Example" in result or "# " in result or "example" in result.lower(), (
        "功能缺失: Reader 未返回预期的 markdown 正文抽取结果"
    )


def test_reader_requires_url_param():
    """Reader 调用缺少 url 应抛 TypeError（必填校验）"""
    read_fn = _get_reader_callable()
    with pytest.raises(TypeError):
        read_fn()  # type: ignore[call-arg]


def test_search_returns_list_for_retrieved_query(monkeypatch, tmp_path):
    """Search 给定真实候选时返回列表，而不是伪造断网结果。"""
    mod = _get_search_module()
    monkeypatch.setattr(mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(mod, "_fetch_candidates", lambda query, num: [_retrieved_candidate(query)], raising=False)
    search_fn = mod.search_web
    results = search_fn(query="jina ai embeddings")
    assert isinstance(results, list), "功能缺失: search_web 应返回 list"
    assert len(results) > 0, "功能缺失: search_web 对常见 query 应返回非空列表"
    assert results[0]["source"] == "searxng"


def test_search_result_items_contain_retrieval_provenance(monkeypatch, tmp_path):
    """Search 单条真实结果需包含 MCP 字段与检索来源。"""
    mod = _get_search_module()
    monkeypatch.setattr(mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(mod, "_fetch_candidates", lambda query, num: [_retrieved_candidate(query)], raising=False)
    search_fn = mod.search_web
    results = search_fn(query="openai gpt-4")
    assert isinstance(results, list) and len(results) > 0
    first = results[0]
    assert isinstance(first, dict), "功能缺失: search 结果项应为 dict"
    for field in ("title", "url", "content"):
        assert field in first, f"功能缺失: search 结果项缺少字段 {field}，实际 {list(first.keys())}"
        assert isinstance(first[field], str) and len(first[field]) > 0
    assert first["source"] == "searxng"
    assert first["retrieved_at"] == "2026-09-04T00:00:00Z"


def test_search_requires_query_param():
    """Search 缺少 query 应抛 TypeError"""
    search_fn = _get_search_callable()
    with pytest.raises(TypeError):
        search_fn()  # type: ignore[call-arg]
