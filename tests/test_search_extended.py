"""Search 深度实现 TDD 扩展测试
要求：
- test_search_returns_real_results：对 query="retrieval augmented generation" 返回 list 且每项含 title/url/content 且内容相关
- test_search_parallel：并发 3 query
- test_search_error_empty_query：空 query 抛 ValueError
- test_search_dedup：重复 url 去重
- test_search_result_length：至少返回 5 条，若 SearXNG 未启动则走 fallback 仍需 3+ 条
TDD 红阶段：这些测试在 stub 实现下应 FAIL
"""
import importlib.util
import pathlib
import sys
import json

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATES = [
    ROOT / "mcp-gateway" / "src" / "search.py",
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
    assert path is not None, f"Search 模块不存在 {CANDIDATES}"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod, path


def _load_isolated(monkeypatch, tmp_path):
    mod, _ = _load()
    monkeypatch.setattr(mod, "CACHE_DIR", tmp_path)
    return mod


def _candidate(query: str, index: int = 1, host: str = "example.com") -> dict:
    return {
        "title": f"{query} result {index}",
        "url": f"https://{host}/docs/{index}",
        "content": f"Retrieved documentation about {query}.",
        "source": "searxng",
        "retrieved_at": "2026-09-04T00:00:00Z",
    }


def _get_search():
    mod, _ = _load()
    for name in ("search_web", "search"):
        if hasattr(mod, name) and callable(getattr(mod, name)):
            return getattr(mod, name), mod
    pytest.fail("未暴露 search_web")


def _get_parallel():
    mod, _ = _load()
    for name in ("parallel_search_web", "parallel_search", "batch_search_web"):
        if hasattr(mod, name) and callable(getattr(mod, name)):
            return getattr(mod, name), mod
    return None, mod


def test_search_returns_only_provenanced_retrieved_results(monkeypatch, tmp_path):
    """search_web 只能返回有来源和检索时间的真实候选。"""
    mod = _load_isolated(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "_fetch_candidates", lambda query, num: [_candidate(query, i) for i in range(1, num + 1)], raising=False)
    search_fn = mod.search_web
    results = search_fn(query="retrieval augmented generation")
    assert isinstance(results, list), "search_web 应返回 list"
    assert len(results) >= 3, f"至少返回 3 条，实际 {len(results)}"
    for item in results:
        assert isinstance(item, dict), "结果项应为 dict"
        for field in ("title", "url", "content"):
            assert field in item, f"缺少字段 {field}, 实际 {list(item.keys())}"
            assert isinstance(item[field], str) and len(item[field].strip()) > 0, f"字段 {field} 应为非空 str"
        assert item["source"] == "searxng"
        assert item["retrieved_at"] == "2026-09-04T00:00:00Z"
    # 内容相关：至少 50% 的结果 title/content 含 query 关键词任一
    q_words = ["retrieval", "augmented", "generation"]
    hits = 0
    for item in results:
        combined = (item.get("title", "") + " " + item.get("content", "")).lower()
        if any(w in combined for w in q_words):
            hits += 1
    assert hits >= len(results) * 0.5, f"相关性不足：仅 {hits}/{len(results)} 命中 query 关键词"


def test_search_parallel(monkeypatch, tmp_path):
    """并发 3 query"""
    mod = _load_isolated(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "_fetch_candidates", lambda query, num: [_candidate(query, 1)], raising=False)
    fn = mod.parallel_search_web
    assert fn is not None, f"功能缺失: 未暴露 parallel_search_web，检查 {CANDIDATES}"
    import inspect
    sig = inspect.signature(fn)
    assert len(sig.parameters) >= 1
    queries = ["retrieval augmented generation", "Qwen3 embedding 0.6B", "jina ai reader"]
    results = fn(queries)
    # 也支持 keyword
    if results is None:
        results = fn(queries=queries)
    assert isinstance(results, list) and len(results) == 3, f"parallel 应返回 3 组结果，实际 {results}"
    for group in results:
        assert isinstance(group, list) and len(group) >= 1, "每组应至少 1 条"
        for item in group:
            assert isinstance(item, dict)
            for field in ("title", "url", "content"):
                assert field in item
            assert item["source"] == "searxng"


def test_search_error_empty_query():
    """空 query 抛 ValueError（严格校验）"""
    search_fn, _ = _get_search()
    with pytest.raises(ValueError):
        search_fn(query="")
    with pytest.raises(ValueError):
        search_fn(query="   ")
    with pytest.raises(ValueError):
        search_fn(query=None)  # type: ignore


def test_search_dedup():
    """重复 url 去重（url 归一化）"""
    # 通过 mock SearXNG 返回重复 url 的场景，或直接调用去重逻辑
    # 由于真实环境 SearXNG 可能未启动，走 fallback 的 stub 默认无重复，故我们测试 dedup 函数或 search_web 的去重能力
    # 策略：若 search 模块暴露 _dedup 或 _normalize_url，则直接测试；否则构造重复场景验证 search 不返回重复 url
    mod, _ = _load()
    # 若暴露 dedup helper
    if hasattr(mod, "_dedup_results") or hasattr(mod, "_dedup") or hasattr(mod, "dedup"):
        dedup_fn = getattr(mod, "_dedup_results", None) or getattr(mod, "_dedup", None) or getattr(mod, "dedup")
        sample = [
            {"title": "a", "url": "https://example.com/a", "content": "c1"},
            {"title": "a dup", "url": "https://example.com/a/", "content": "c2"},
            {"title": "b", "url": "https://example.com/a#frag", "content": "c3"},
            {"title": "c", "url": "https://example.com/b", "content": "c4"},
        ]
        out = dedup_fn(sample)
        urls = [r["url"] for r in out]
        # 归一化后 example.com/a 的三种变体应去重为 1 条
        assert len(out) == 2, f"去重失败，期望 2 条，实际 {len(out)} urls={urls}"
        return
    if hasattr(mod, "_normalize_url"):
        norm = mod._normalize_url
        assert norm("https://example.com/a/") == norm("https://example.com/a")
        assert norm("https://example.com/a#frag") == norm("https://example.com/a")
    # 回退：验证真实 search 结果无重复 url（归一化后）
    search_fn, _ = _get_search()
    results = search_fn(query="retrieval augmented generation", num=5) if "num" in __import__("inspect").signature(search_fn).parameters else search_fn(query="retrieval augmented generation")
    # 归一化去重检查
    def _norm(u: str) -> str:
        import urllib.parse
        p = urllib.parse.urlparse(u.strip())
        netloc = p.netloc.lower()
        path = p.path.rstrip("/") or "/"
        # 去掉 fragment
        return f"{p.scheme.lower()}://{netloc}{path}"

    normalized = [_norm(r["url"]) for r in results]
    assert len(normalized) == len(set(normalized)), f"返回结果存在重复 url（归一化后）：{normalized}"


def test_search_result_length_and_cache_envelope(monkeypatch, tmp_path):
    """成功结果精确截断，并以带过期时间的 provenance cache 保存。"""
    mod = _load_isolated(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "_fetch_candidates", lambda query, num: [_candidate(query, i) for i in range(1, 8)], raising=False)
    search_fn = mod.search_web
    import inspect
    sig = inspect.signature(search_fn)
    # 支持 num 参数
    assert "num" in sig.parameters or "top_k" in sig.parameters or "limit" in sig.parameters, "search_web 应支持 num/top_k/limit 参数以截断 top_k"
    param_name = "num" if "num" in sig.parameters else ("top_k" if "top_k" in sig.parameters else "limit")
    results = search_fn(query="retrieval augmented generation", **{param_name: 5})
    assert isinstance(results, list)
    assert len(results) == 5, f"num=5 应精确返回 5 条，实际 {len(results)}"
    # 验证 top_k 截断
    results3 = search_fn(query="retrieval augmented generation", **{param_name: 3})
    assert len(results3) == 3, f"top_k=3 应精确返回 3 条，实际 {len(results3)}"

    q = "retrieval augmented generation"
    cache_file = mod._cache_path(q)
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert data["query"] == q
    assert data["expires_at"] > data["created_at"]
    assert data["results"] == results


def test_search_rejects_synthetic_legacy_cache_and_surfaces_unavailability(monkeypatch, tmp_path):
    """旧 list cache 的伪造内容不可返回，且无后端时必须明确报错。"""
    mod = _load_isolated(monkeypatch, tmp_path)
    query = "OpenCode official documentation"
    cache_file = mod._cache_path(query)
    cache_file.write_text(json.dumps([{
        "title": query,
        "url": "https://jina.ai/topics/opencode/123",
        "content": f"This result discusses {query} in depth.",
    }]), encoding="utf-8")
    monkeypatch.setattr(mod, "_fetch_candidates", lambda query, num: [], raising=False)
    with pytest.raises(mod.SearchUnavailableError, match="NO_RETRIEVAL_BACKEND"):
        mod.search_web(query)
    assert not cache_file.exists()


def test_search_enforces_site_operator(monkeypatch, tmp_path):
    """site: 查询只能返回目标域名及其子域名。"""
    mod = _load_isolated(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "_fetch_candidates", lambda query, num: [
        _candidate(query, 1, "opencode.ai"),
        _candidate(query, 2, "docs.opencode.ai"),
        _candidate(query, 3, "example.com"),
    ], raising=False)
    results = mod.search_web("site:opencode.ai documentation", num=5)
    assert [item["url"] for item in results] == [
        "https://opencode.ai/docs/1",
        "https://docs.opencode.ai/docs/2",
    ]


def test_searxng_json_request_supplies_client_ip_headers(monkeypatch):
    """SearXNG JSON 请求必须携带本地客户端 IP，避免 limiter 返回 403。"""
    mod, _ = _load()
    calls = []

    class Response:
        status_code = 200

        def json(self):
            return {"results": [{"title": "result", "url": "https://example.com", "content": "ok"}]}

    def fake_get(*args, **kwargs):
        calls.append(kwargs)
        return Response()

    monkeypatch.setattr(mod.requests, "get", fake_get)
    mod._fetch_searxng("test", 1)
    assert calls
    assert calls[0]["headers"]["X-Real-IP"] == "127.0.0.1"
    assert calls[0]["headers"]["X-Forwarded-For"] == "127.0.0.1"
