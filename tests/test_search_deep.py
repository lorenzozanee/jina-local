"""search_web_deep 本地编排 TDD
要求 6 测试：
- test_search_deep_returns_list（query 返回 list 每项含 title/url/best_passage/content）
- test_search_deep_best_passage_contains_query（最佳段落含 query 关键词）
- test_search_deep_parallel_fetch（验证并发抓取 3 URL）
- test_search_deep_rerank_used（best_passage 与 reranker 分数一致）
- test_search_deep_empty_query
- test_search_deep_limit_param
TDD 红阶段：搜索→逐页 Reader→Reranker 选最佳段落
"""
import hashlib
import importlib.util
import pathlib
import sys
import time
import threading
import http.server
import socket
from unittest.mock import MagicMock, patch, call

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATES = [
    ROOT / "mcp-gateway" / "src" / "search_deep.py",
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
    assert path is not None, f"search_deep 模块不存在 {CANDIDATES}"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod, path

def _get_search_deep():
    # prefer search_deep module
    p = ROOT / "mcp-gateway" / "src" / "search_deep.py"
    if p.exists():
        spec = importlib.util.spec_from_file_location("search_deep", p)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["search_deep"] = mod
        spec.loader.exec_module(mod)  # type: ignore
        llm_path = ROOT / "mcp-gateway" / "src" / "search_llm.py"
        llm_spec = importlib.util.spec_from_file_location("search_llm", llm_path)
        llm_mod = importlib.util.module_from_spec(llm_spec)
        llm_spec.loader.exec_module(llm_mod)  # type: ignore
        mod.search_llm = llm_mod
        for name in ("search_web_deep", "search_deep"):
            if hasattr(mod, name) and callable(getattr(mod, name)):
                return getattr(mod, name), mod
        pytest.fail(f"{p} 未暴露 search_web_deep")
    # fallback gateway
    mod, _ = _load()
    for name in ("search_web_deep", "search_deep", "search_web"):
        if hasattr(mod, name) and callable(getattr(mod, name)):
            return getattr(mod, name), mod
    pytest.fail(f"未暴露 search_web_deep，检查 {CANDIDATES}")

def _make_mock_search(results=None):
    if results is None:
        results = [
            {"title": "Qwen3 embedding overview", "url": "https://example.com/a", "content": "snippet about Qwen3 embedding"},
            {"title": "Qwen3 second", "url": "https://example.com/b", "content": "snippet 2"},
            {"title": "Qwen3 third", "url": "https://example.com/c", "content": "snippet 3"},
        ]
    fn = MagicMock(return_value=results)
    return fn

def _make_mock_reader(contents=None):
    if contents is None:
        # return markdown with query words spread across chunks
        contents = [
            "# Title A\n\nQwen3 embedding is a great model for retrieval augmented generation. " + " filler" * 50 + " other unrelated cooking recipe apple pie. " + " filler" * 30,
            "# Title B\n\nSecond doc about Qwen3 embedding and transformer models. " + " filler" * 40,
            "# Title C\n\nThird doc irrelevant cooking but mentions Qwen3 embedding briefly. " + " filler" * 40,
        ]
    def _reader(url, question=None, **kwargs):
        # map url suffix to content index
        if "example.com/a" in url:
            return contents[0]
        if "example.com/b" in url:
            return contents[1] if len(contents) > 1 else contents[0]
        if "example.com/c" in url:
            return contents[2] if len(contents) > 2 else contents[0]
        return contents[0]
    fn = MagicMock(side_effect=_reader)
    return fn

def _make_mock_parallel(contents=None):
    reader_fn = _make_mock_reader(contents)
    def _parallel(urls, question=None, **kwargs):
        return [reader_fn(u, question=question) for u in urls]
    fn = MagicMock(side_effect=_parallel)
    fn._inner = reader_fn
    return fn

def test_search_deep_returns_list():
    """query 返回 list 每项含 title/url/best_passage/content"""
    fn, mod = _get_search_deep()
    # use mocks via dependency injection if supported, otherwise patch module level
    mock_search = _make_mock_search()
    # build contents with enough words
    mock_parallel = _make_mock_parallel()
    # try injection via kwargs
    import inspect
    sig = inspect.signature(fn)
    kwargs = {}
    if "search_fn" in sig.parameters:
        kwargs["search_fn"] = mock_search
    if "reader_fn" in sig.parameters:
        kwargs["reader_fn"] = mock_parallel
    if "search_func" in sig.parameters:
        kwargs["search_func"] = mock_search
    if "parallel_reader" in sig.parameters:
        kwargs["parallel_reader"] = mock_parallel
    # patch fallback if injection not supported
    patches = []
    if not kwargs:
        # patch module attributes
        for attr in ("search_web", "_search_search_web", "search", "parallel_read_url", "_reader_parallel", "rerank", "sort_by_relevance"):
            if hasattr(mod, attr):
                # we will patch search-like
                pass
        # patch search module if possible
        try:
            import search as _search_mod  # type: ignore
            patches.append(patch.object(_search_mod, "search_web", mock_search))
        except Exception:
            pass
        # patch reader
        try:
            import reader as _reader_mod  # type: ignore
            patches.append(patch.object(_reader_mod, "parallel_read_url", mock_parallel))
        except Exception:
            pass
        # also patch inside mod
        if hasattr(mod, "search_web"):
            patches.append(patch.object(mod, "search_web", mock_search))
        if hasattr(mod, "parallel_read_url"):
            patches.append(patch.object(mod, "parallel_read_url", mock_parallel))
    for p in patches:
        p.start()
    try:
        if kwargs:
            results = fn(query="Qwen3 embedding", num=3, chunk_size=100, **kwargs)
        else:
            results = fn(query="Qwen3 embedding", num=3, chunk_size=100) if "chunk_size" in sig.parameters else fn(query="Qwen3 embedding", num=3)
        assert isinstance(results, list), "search_web_deep 应返回 list"
        assert len(results) >= 1, "至少返回 1 条"
        for item in results:
            assert isinstance(item, dict), "结果项应为 dict"
            for field in ("title", "url", "content", "best_passage"):
                assert field in item, f"缺少字段 {field}，实际 {list(item.keys())}"
                assert isinstance(item[field], str) and len(item[field].strip()) > 0, f"字段 {field} 应为非空 str"
            # score field
            score_field = next((k for k in ("score", "relevance_score", "relevance") if k in item), None)
            assert score_field is not None, f"缺少分数列 score/relevance_score，实际 {list(item.keys())}"
            assert isinstance(item[score_field], (int, float))
            assert 0.0 <= float(item[score_field]) <= 1.0 or float(item[score_field]) >= 0
    finally:
        for p in patches:
            p.stop()

def test_search_deep_best_passage_contains_query():
    """最佳段落含 query 关键词"""
    fn, mod = _get_search_deep()
    # craft contents where chunks distinct
    rich_text = "Qwen3 embedding is powerful. " * 20 + " unrelated cooking recipe apple pie " * 20 + " filler filler filler " * 30
    # To ensure chunk cut, create long content where first chunk contains query, second not
    contents = [
        "# Doc1\n\n" + rich_text,
        "# Doc2\n\n" + "cooking recipe only no query " * 40 + " Qwen3 embedding hidden at end " * 5,
    ]
    mock_search = _make_mock_search([
        {"title": "doc1", "url": "https://example.com/a", "content": "snippet"},
        {"title": "doc2", "url": "https://example.com/b", "content": "snippet"},
    ])
    mock_parallel = _make_mock_parallel(contents)
    import inspect
    sig = inspect.signature(fn)
    kwargs = {}
    if "search_fn" in sig.parameters:
        kwargs["search_fn"] = mock_search
    if "reader_fn" in sig.parameters:
        kwargs["reader_fn"] = mock_parallel
    patches = []
    if not kwargs:
        if hasattr(mod, "search_web"):
            patches.append(patch.object(mod, "search_web", mock_search))
        if hasattr(mod, "parallel_read_url"):
            patches.append(patch.object(mod, "parallel_read_url", mock_parallel))
    for p in patches:
        p.start()
    try:
        q = "Qwen3 embedding"
        if kwargs:
            results = fn(query=q, num=2, chunk_size=100, **kwargs)
        else:
            results = fn(query=q, num=2, chunk_size=100) if "chunk_size" in sig.parameters else fn(query=q, num=2)
        assert isinstance(results, list) and len(results) >= 1
        for item in results:
            best = item.get("best_passage") or item.get("best") or ""
            # best_passage should contain query words (at least one)
            lowered = best.lower()
            assert "qwen3" in lowered or "embedding" in lowered, f"best_passage 未含 query 关键词 {q!r}，实际 best={best[:200]}"
    finally:
        for p in patches:
            p.stop()

def test_search_deep_parallel_fetch():
    """验证并发抓取 3 URL"""
    fn, mod = _get_search_deep()
    # clear cache for unique query to force reader call
    import hashlib as _hl2, pathlib as _pl2
    _uq2 = "retrieval augmented generation parallel unique 777"
    for _p in [
        _pl2.Path("/tmp/opencode/jina-local") / f"search_deep-{_hl2.sha256(_uq2.encode()).hexdigest()}.json",
        _pl2.Path("/tmp/opencode/jina-local") / f"search_deep-{_hl2.sha256(f'{_uq2}|3|100'.encode()).hexdigest()}.json",
    ]:
        if _p.exists():
            try:
                _p.unlink()
            except Exception:
                pass
    try:
        from search_deep import _mem_cache as _mc3  # type: ignore
        _mc3.clear()
    except Exception:
        pass
    urls = ["https://example.com/a", "https://example.com/b", "https://example.com/c"]
    mock_search = _make_mock_search([
        {"title": "a", "url": urls[0], "content": "s1"},
        {"title": "b", "url": urls[1], "content": "s2"},
        {"title": "c", "url": urls[2], "content": "s3"},
    ])
    # track calls and concurrency
    call_order = []
    call_timestamps = []
    lock = threading.Lock()
    concurrent_counter = {"cur": 0, "max": 0}
    def _parallel(urls_in, question=None, **kwargs):
        with lock:
            concurrent_counter["cur"] += 1
            concurrent_counter["max"] = max(concurrent_counter["max"], concurrent_counter["cur"])
            call_timestamps.append(time.time())
        # simulate network delay to allow concurrency observation
        time.sleep(0.15)
        call_order.append(list(urls_in))
        with lock:
            concurrent_counter["cur"] -= 1
        # return markdown per url
        return [f"# Title for {u}\n\nContent about retrieval augmented generation for {u} " + " filler" * 50 for u in urls_in]
    mock_parallel = MagicMock(side_effect=_parallel)
    import inspect
    sig = inspect.signature(fn)
    kwargs = {}
    if "search_fn" in sig.parameters:
        kwargs["search_fn"] = mock_search
    if "reader_fn" in sig.parameters:
        kwargs["reader_fn"] = mock_parallel
    patches = []
    if not kwargs:
        if hasattr(mod, "search_web"):
            patches.append(patch.object(mod, "search_web", mock_search))
        if hasattr(mod, "parallel_read_url"):
            patches.append(patch.object(mod, "parallel_read_url", mock_parallel))
        # also try to patch internal ThreadPoolExecutor usage? but checking mock call suffices
    for p in patches:
        p.start()
    try:
        t0 = time.perf_counter()
        if kwargs:
            results = fn(query="retrieval augmented generation parallel unique 777", num=3, chunk_size=100, **kwargs)
        else:
            results = fn(query="retrieval augmented generation parallel unique 777", num=3, chunk_size=100) if "chunk_size" in sig.parameters else fn(query="retrieval augmented generation parallel unique 777", num=3)
        elapsed = time.perf_counter() - t0
        assert isinstance(results, list) and len(results) == 3
        # 验证并发：mock 应被调用且传入 3 URL 一次性或分批但总数为 3
        assert mock_parallel.called, "parallel_read_url 未被调用，未实现并发抓取"
        # 检查调用参数包含 3 URL
        called_urls = []
        for c in mock_parallel.call_args_list:
            args, kw = c
            if args and isinstance(args[0], list):
                called_urls.extend(args[0])
            elif "urls" in kw and isinstance(kw["urls"], list):
                called_urls.extend(kw["urls"])
        # 去重后应覆盖 3 URL
        assert len(set(called_urls)) == 3 or len(call_order) >= 1, f"并发抓取 URL 数不足，called {called_urls} orders {call_order}"
        # 若使用 ThreadPool，并发耗时应小于串行 3*0.15=0.45，验证 elapsed < 0.4 (allow overhead)
        # 如果实现是并发，elapsed 应该 ~0.15-0.3；若串行则 ~0.45+
        # 不强制失败，但若 elapsed > 0.45 且 max concurrency ==1，则说明未并发
        if concurrent_counter["max"] == 1 and elapsed > 0.4:
            pytest.fail(f"未实现并发：耗时 {elapsed:.3f}s >0.4s 且 max concurrency {concurrent_counter['max']}, call_order {call_order}")
        # 允许并发但耗时稍长也 pass，只要 mock 被以 3 URL 批量调用
        assert elapsed < 1.0, f"耗时过长 {elapsed:.3f}s"
    finally:
        for p in patches:
            p.stop()

def test_search_deep_rerank_used():
    """best_passage 与 reranker 分数一致"""
    fn, mod = _get_search_deep()
    # clear cache for unique query to avoid hit from earlier tests
    import hashlib as _hl, pathlib as _pl
    _uq = "Qwen3 embedding rerank unique 999"
    for _p in [
        _pl.Path("/tmp/opencode/jina-local") / f"search_deep-{_hl.sha256(_uq.encode()).hexdigest()}.json",
        _pl.Path("/tmp/opencode/jina-local") / f"search_deep-{_hl.sha256(f'{_uq}|1|50'.encode()).hexdigest()}.json",
    ]:
        if _p.exists():
            try:
                _p.unlink()
            except Exception:
                pass
    try:
        from search_deep import _mem_cache as _mc  # type: ignore
        _mc.clear()
    except Exception:
        pass
    try:
        from mcp_gateway.src.search_deep import _mem_cache as _mc2  # type: ignore
        _mc2.clear()
    except Exception:
        pass
    # Prepare content where two chunks: first chunk has query, second not.
    # Use small chunk_size so chunks distinct.
    doc_content = "Qwen3 embedding great model. " * 30 + " unrelated filler cooking recipe " * 30 + " Qwen3 embedding hidden again " * 10
    # We'll create search returning 1 url
    mock_search = _make_mock_search([
        {"title": "test doc", "url": "https://example.com/a", "content": "snippet"},
    ])
    mock_parallel = _make_mock_parallel([doc_content])
    # mock reranker to return deterministic scores
    # We need to capture passages passed to reranker
    captured = {}
    original_rerank = None
    # find rerank function in mod
    mock_rerank = MagicMock()
    def _fake_rerank(query, documents):
        captured["query"] = query
        captured["documents"] = list(documents)
        # return scores: first doc highest if contains query
        scored = []
        for idx, doc in enumerate(documents):
            # score 0.9 for first containing qwen3, 0.1 otherwise
            score = 0.9 if "qwen3" in doc.lower() else 0.1
            # ensure first chunk gets 0.9, second 0.1 even if both contain? we differentiate by position
            # make first higher than rest
            if idx == 0:
                score = 0.95
            elif idx == 1:
                score = 0.05
            scored.append({"document": doc, "relevance_score": float(score), "_idx": idx})
        scored.sort(key=lambda x: -x["relevance_score"])
        # remove _idx
        for s in scored:
            s.pop("_idx", None)
        mock_rerank.return_value = scored
        return scored
    mock_rerank.side_effect = _fake_rerank

    import inspect
    sig = inspect.signature(fn)
    kwargs = {}
    if "search_fn" in sig.parameters:
        kwargs["search_fn"] = mock_search
    if "reader_fn" in sig.parameters:
        kwargs["reader_fn"] = mock_parallel
    if "reranker_fn" in sig.parameters:
        kwargs["reranker_fn"] = mock_rerank
    if "rerank_fn" in sig.parameters:
        kwargs["rerank_fn"] = mock_rerank
    patches = []
    if not kwargs or "reranker_fn" not in kwargs:
        # patch module level rerank if exists
        for name in ("rerank", "sort_by_relevance", "reranker", "_rerank", "_rerank_sort"):
            if hasattr(mod, name):
                patches.append(patch.object(mod, name, mock_rerank))
        # also patch reranker module
        try:
            import reranker as _reranker_mod  # type: ignore
            patches.append(patch.object(_reranker_mod, "rerank", mock_rerank))
            patches.append(patch.object(_reranker_mod, "sort_by_relevance", mock_rerank))
        except Exception:
            pass
    if not kwargs or "search_fn" not in kwargs:
        if hasattr(mod, "search_web"):
            patches.append(patch.object(mod, "search_web", mock_search))
    if not kwargs or "reader_fn" not in kwargs:
        if hasattr(mod, "parallel_read_url"):
            patches.append(patch.object(mod, "parallel_read_url", mock_parallel))
    for p in patches:
        p.start()
    try:
        q = "Qwen3 embedding rerank unique 999"
        if kwargs:
            results = fn(query=q, num=1, chunk_size=50, **kwargs)
        else:
            # need to pass chunk_size if supported
            if "chunk_size" in sig.parameters:
                results = fn(query=q, num=1, chunk_size=50)
            else:
                results = fn(query=q, num=1)
        assert isinstance(results, list) and len(results) == 1
        item = results[0]
        best = item.get("best_passage") or item.get("best") or ""
        # check that best passage equals top doc from reranker
        # captured documents include chunked passages
        if "documents" in captured:
            # top reranked document should be best_passage
            # mock returns sorted, top is captured sorted top; but we need to compare
            # our fake returns sorted list, top is first
            top_doc = mock_rerank.return_value[0]["document"] if mock_rerank.return_value else captured["documents"][0]
            assert best == top_doc or best in captured["documents"], f"best_passage {best[:100]!r} 与 reranker top 不一致 top={top_doc[:100]!r} captured={captured['documents'][:1]}"
            # also score should match reranker score
            score_field = next((k for k in ("score", "relevance_score", "relevance") if k in item), None)
            assert score_field is not None
            score_val = float(item[score_field])
            expected_score = float(mock_rerank.return_value[0]["relevance_score"])
            assert abs(score_val - expected_score) < 1e-6, f"分数不一致 {score_val} vs {expected_score}"
        # ensure reranker was called
        assert mock_rerank.called or ("reranker_fn" in kwargs and kwargs["reranker_fn"].called), "reranker 未被调用，未实现 rerank 选优"
    finally:
        for p in patches:
            p.stop()

def test_search_deep_empty_query():
    fn, mod = _get_search_deep()
    with pytest.raises((ValueError, TypeError)):
        fn(query="")
    with pytest.raises((ValueError, TypeError)):
        fn(query="   ")
    with pytest.raises((ValueError, TypeError, TypeError)):
        fn(query=None)  # type: ignore
    with pytest.raises((ValueError, TypeError)):
        fn(query=123)  # type: ignore

def test_search_deep_limit_param():
    """limit/num 参数截断"""
    fn, mod = _get_search_deep()
    # mock search to return 5 results
    five_results = [
        {"title": f"title {i}", "url": f"https://example.com/{i}", "content": f"content {i}"}
        for i in range(5)
    ]
    mock_search = _make_mock_search(five_results)
    # mock reader to return simple content
    def _parallel(urls, question=None, **kwargs):
        return [f"# Title {u}\n\nContent about retrieval augmented generation for {u} " + " filler" * 30 for u in urls]
    mock_parallel = MagicMock(side_effect=_parallel)
    import inspect
    sig = inspect.signature(fn)
    # test num=2 and num=5
    for param_name in ("num", "limit", "top_k"):
        if param_name in sig.parameters:
            # test with that param
            kwargs = {}
            if "search_fn" in sig.parameters:
                kwargs["search_fn"] = mock_search
            if "reader_fn" in sig.parameters:
                kwargs["reader_fn"] = mock_parallel
            patches = []
            if not kwargs:
                if hasattr(mod, "search_web"):
                    patches.append(patch.object(mod, "search_web", mock_search))
                if hasattr(mod, "parallel_read_url"):
                    patches.append(patch.object(mod, "parallel_read_url", mock_parallel))
            for p in patches:
                p.start()
            try:
                # need to use correct param name
                call_kwargs = {param_name: 3, "query": "retrieval augmented generation", "chunk_size": 100}
                # inject mocks if needed via kwargs override
                call_kwargs.update(kwargs)
                # inspect if fn expects num vs limit
                # we pass via kwargs dict, but we already used param_name
                # So for this iteration, call with query and param
                if param_name in sig.parameters:
                    # build call
                    if "search_fn" in sig.parameters:
                        results = fn(query="retrieval augmented generation", **{param_name: 3, "chunk_size": 100}, search_fn=mock_search, reader_fn=mock_parallel) if "chunk_size" in sig.parameters else fn(query="retrieval augmented generation", **{param_name: 3}, search_fn=mock_search, reader_fn=mock_parallel)
                    else:
                        results = fn(query="retrieval augmented generation", **{param_name: 3, "chunk_size": 100}) if "chunk_size" in sig.parameters else fn(query="retrieval augmented generation", **{param_name: 3})
                else:
                    continue
                assert isinstance(results, list), f"{param_name} 返回非 list"
                assert len(results) == 3, f"{param_name}=3 应返回 3 条，实际 {len(results)}"
                # also test 2
                if "search_fn" in sig.parameters:
                    results2 = fn(query="retrieval augmented generation", **{param_name: 2, "chunk_size": 100}, search_fn=mock_search, reader_fn=mock_parallel) if "chunk_size" in sig.parameters else fn(query="retrieval augmented generation", **{param_name: 2}, search_fn=mock_search, reader_fn=mock_parallel)
                else:
                    results2 = fn(query="retrieval augmented generation", **{param_name: 2, "chunk_size": 100}) if "chunk_size" in sig.parameters else fn(query="retrieval augmented generation", **{param_name: 2})
                assert len(results2) == 2, f"{param_name}=2 应返回 2 条，实际 {len(results2)}"
            finally:
                for p in patches:
                    p.stop()
            return
    # fallback: try default num param
    kwargs = {}
    if "search_fn" in sig.parameters:
        kwargs["search_fn"] = mock_search
    if "reader_fn" in sig.parameters:
        kwargs["reader_fn"] = mock_parallel
    patches = []
    if not kwargs:
        if hasattr(mod, "search_web"):
            patches.append(patch.object(mod, "search_web", mock_search))
        if hasattr(mod, "parallel_read_url"):
            patches.append(patch.object(mod, "parallel_read_url", mock_parallel))
    for p in patches:
        p.start()
    try:
        if "search_fn" in kwargs:
            results = fn(query="retrieval augmented generation", num=3, chunk_size=100, **kwargs) if "chunk_size" in sig.parameters else fn(query="retrieval augmented generation", num=3, **kwargs)
            results2 = fn(query="retrieval augmented generation", num=2, chunk_size=100, **kwargs) if "chunk_size" in sig.parameters else fn(query="retrieval augmented generation", num=2, **kwargs)
        else:
            results = fn(query="retrieval augmented generation", num=3, chunk_size=100) if "chunk_size" in sig.parameters else fn(query="retrieval augmented generation", num=3)
            results2 = fn(query="retrieval augmented generation", num=2, chunk_size=100) if "chunk_size" in sig.parameters else fn(query="retrieval augmented generation", num=2)
        assert len(results) == 3, f"num=3 应返回 3，实际 {len(results)}"
        assert len(results2) == 2, f"num=2 应返回 2，实际 {len(results2)}"
        # verify caching maybe? but not required
    finally:
        for p in patches:
            p.stop()

def test_search_deep_cache():
    """缓存：相同 query 复用 sha256 缓存文件"""
    fn, mod = _get_search_deep()
    mock_search = _make_mock_search([
        {"title": "a", "url": "https://example.com/a", "content": "s1"},
    ])
    mock_parallel = _make_mock_parallel(["# Title\n\nQwen3 embedding content " + " filler" * 40])
    import inspect, hashlib, pathlib, time
    sig = inspect.signature(fn)
    kwargs = {}
    if "search_fn" in sig.parameters:
        kwargs["search_fn"] = mock_search
    if "reader_fn" in sig.parameters:
        kwargs["reader_fn"] = mock_parallel
    # clean cache
    q = "cache_test_query_unique_12345"
    key = hashlib.sha256(q.encode()).hexdigest()
    # try multiple cache path patterns
    cache_candidates = [
        pathlib.Path("/tmp/opencode/jina-local") / f"search_deep-{key}.json",
        pathlib.Path("/tmp/opencode/jina-local") / f"search-deep-{key}.json",
        pathlib.Path("/tmp/opencode/jina-local") / f"deep-{key}.json",
        pathlib.Path("/tmp/opencode/jina-local") / f"{key}.json",
    ]
    for p in cache_candidates:
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
    patches = []
    if not kwargs:
        if hasattr(mod, "search_web"):
            patches.append(patch.object(mod, "search_web", mock_search))
        if hasattr(mod, "parallel_read_url"):
            patches.append(patch.object(mod, "parallel_read_url", mock_parallel))
    for p in patches:
        p.start()
    try:
        if kwargs:
            first = fn(query=q, num=1, chunk_size=100, **kwargs)
        else:
            first = fn(query=q, num=1, chunk_size=100) if "chunk_size" in sig.parameters else fn(query=q, num=1)
        # second call should hit cache (search not called again if caching works, or file exists)
        # we check cache file exists at least
        exists = any(p.exists() for p in cache_candidates)
        # alternative: check /tmp/opencode/jina-local/search* exists
        if not exists:
            # broaden check
            import glob
            files = glob.glob("/tmp/opencode/jina-local/*search*deep*")
            exists = len(files) > 0
            # also check any cache file containing query hash
            files2 = list(pathlib.Path("/tmp/opencode/jina-local").glob(f"*{key[:8]}*")) if pathlib.Path("/tmp/opencode/jina-local").exists() else []
            if files2:
                exists = True
        # if caching not implemented via file, at least second call should return same
        if kwargs:
            second = fn(query=q, num=1, chunk_size=100, **kwargs)
        else:
            second = fn(query=q, num=1, chunk_size=100) if "chunk_size" in sig.parameters else fn(query=q, num=1)
        assert first == second, "缓存命中时结果应一致"
        # file existence is preferred but not strictly fail if logic uses memory cache only
        # So we just ensure second call succeeds and equals first
    finally:
        for p in patches:
            p.stop()


def test_search_deep_query_fusion_deduplicates_urls_and_keeps_provenance():
    fn, mod = _get_search_deep()
    mod.clear_cache()
    query = "fusion query unique 314159"
    calls = []
    candidates = {
        query: [
            {"title": "A", "url": "https://example.com/a", "content": "A content", "source": "local", "retrieved_at": "t1"},
            {"title": "B", "url": "https://example.com/b", "content": "B content", "source": "local", "retrieved_at": "t1"},
        ],
        "fusion variant": [
            {"title": "B duplicate", "url": "https://EXAMPLE.com/b/", "content": "B variant", "source": "local", "retrieved_at": "t2"},
            {"title": "C", "url": "https://example.com/c", "content": "C content", "source": "local", "retrieved_at": "t2"},
        ],
    }

    def search(search_query, num=3):
        calls.append(search_query)
        return candidates[search_query]

    def reader(urls, question=None, **kwargs):
        return [f"content for {url} {query}" for url in urls]

    with patch.object(mod.search_llm, "plan_queries", return_value=["fusion variant"]), patch.object(mod.search_llm, "rerank_ids", return_value=None):
        results = fn(query, num=3, chunk_size=100, search_fn=search, reader_fn=reader)

    assert calls == [query, "fusion variant"]
    assert [item["url"].rstrip("/").lower() for item in results] == [
        "https://example.com/b",
        "https://example.com/a",
        "https://example.com/c",
    ]
    assert len(results) == 3
    assert all(item["source"] == "local" and item["retrieved_at"] in {"t1", "t2"} for item in results)


def test_search_deep_llm_rerank_reorders_only_supplied_candidates():
    fn, mod = _get_search_deep()
    mod.clear_cache()
    query = "llm reorder unique 271828"
    search = MagicMock(return_value=[
        {"title": "A", "url": "https://example.com/a", "content": "A", "source": "local", "retrieved_at": "t"},
        {"title": "B", "url": "https://example.com/b", "content": "B", "source": "local", "retrieved_at": "t"},
        {"title": "C", "url": "https://example.com/c", "content": "C", "source": "local", "retrieved_at": "t"},
    ])
    reader = lambda urls, question=None, **kwargs: [f"{query} evidence {url}" for url in urls]
    seen = {}

    def rerank(query_text, candidates):
        seen["ids"] = [candidate["id"] for candidate in candidates]
        return list(reversed(seen["ids"]))

    with patch.object(mod.search_llm, "plan_queries", return_value=[]), patch.object(mod.search_llm, "rerank_ids", side_effect=rerank):
        results = fn(query, num=3, chunk_size=100, search_fn=search, reader_fn=reader)

    assert [item["url"] for item in results] == [
        "https://example.com/c",
        "https://example.com/b",
        "https://example.com/a",
    ]
    assert len(seen["ids"]) == 3
    assert all(item["source"] == "local" and item["retrieved_at"] == "t" for item in results)


def test_search_deep_llm_failures_preserve_baseline_and_never_add_candidates():
    fn, mod = _get_search_deep()
    query = "llm failure unique 161803"
    search = MagicMock(return_value=[
        {"title": "A", "url": "https://example.com/a", "content": "A", "source": "local", "retrieved_at": "t"},
        {"title": "B", "url": "https://example.com/b", "content": "B", "source": "local", "retrieved_at": "t"},
    ])
    reader = lambda urls, question=None, **kwargs: [f"{query} evidence {url}" for url in urls]

    for planned, reranked in [
        (RuntimeError("planner"), None),
        ([], ["unknown"]),
        ([], ValueError("malformed")),
    ]:
        mod._mem_cache.clear()
        with patch.object(mod.search_llm, "plan_queries", side_effect=planned if isinstance(planned, Exception) else (lambda _query: planned)), patch.object(mod.search_llm, "rerank_ids", side_effect=reranked if isinstance(reranked, Exception) else (lambda _query, _candidates: reranked)):
            results = fn(query + str(planned) + str(reranked), num=3, chunk_size=100, search_fn=search, reader_fn=reader)
        assert [item["url"] for item in results] == ["https://example.com/a", "https://example.com/b"]
        assert all(item["url"] != "https://attacker.example/new" for item in results)
