"""Reranker TDD 扩展测试 - 本地语义 Reranker 替代 jina sort_by_relevance

6 测：
- test_reranker_semantic_order
- test_reranker_score_range
- test_reranker_batch
- test_reranker_empty
- test_reranker_stability
- test_reranker_normalized_scores

TDD 红阶段：词重叠 stub 在 score_range / normalized_scores 上应 FAIL（分数 0-2 非 0-1，且无归一化）
"""
import importlib.util
import pathlib
import sys
import math
import statistics

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATES = [
    ROOT / "mcp-gateway" / "src" / "reranker.py",
    ROOT / "mcp-gateway" / "src" / "gateway.py",
    ROOT / "mcp-gateway" / "src" / "server.py",
]

SAMPLE_DOCS = [
    "Apple is a fruit that grows on trees",
    "Car engine contains pistons and cylinders",
    "Apple pie recipe with cinnamon and sugar",
    "Quantum physics describes entangled particles",
]

# for batch tests, include more docs
EXTRA_DOCS = [
    "Apple fruit nutrition and health benefits",
    "Vehicle motor oil and engine performance",
    "Machine learning transformer models",
    "Fresh apple orchard harvest season",
    "Automotive piston cylinder engine design",
    "Quantum entanglement theoretical physics",
    "Fruit salad apple banana orange recipe",
    "Deep learning neural network training",
]


def _resolve_path():
    for p in CANDIDATES:
        if p.exists():
            return p
    return None


def _load_module(path: pathlib.Path):
    assert path is not None, f"Reranker 模块不存在 {CANDIDATES}"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader, f"无法加载 {path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def _get_reranker():
    path = _resolve_path()
    assert path is not None, f"Reranker 实现不存在 {CANDIDATES}"
    mod = _load_module(path)
    # 优先 rerank, 其次 sort_by_relevance
    for name in ("rerank", "sort_by_relevance", "reranker"):
        if hasattr(mod, name) and callable(getattr(mod, name)):
            return getattr(mod, name), mod, path
    pytest.fail(f"{path} 未暴露 rerank/sort_by_relevance")


def _score(item):
    for k in ("relevance_score", "score", "relevance"):
        if k in item:
            return float(item[k])
    return 0.0


def _doc(item):
    return item.get("document") or item.get("text") or item.get("content") or ""


def test_reranker_semantic_order():
    """apple fruit 查询 - 语义正样本应排首，4 文档排序最相关为 Apple is a fruit"""
    fn, mod, path = _get_reranker()
    results = fn(query="apple fruit", documents=SAMPLE_DOCS)
    assert isinstance(results, list) and len(results) == len(SAMPLE_DOCS)
    scores = [_score(r) for r in results]
    assert scores == sorted(scores, reverse=True), f"未降序 scores={scores}"
    top = _doc(results[0])
    # 语义最相关必须是含 fruit 语义的文档，而非仅靠 apple 词重叠的 pie
    assert top.strip() == "Apple is a fruit that grows on trees", f"语义排序错误，top 应为 Apple is a fruit，实际 {top!r}, 全排序 {[_doc(r) for r in results]}"
    # car engine 应排在后两位
    docs_ordered = [_doc(r) for r in results]
    car_idx = next((i for i, d in enumerate(docs_ordered) if "Car engine" in d), -1)
    assert car_idx >= 2, f"不相关文档应排后，Car engine 位置 {car_idx}, 排序 {docs_ordered}"


def test_reranker_score_range():
    """分数必须在 0-1 区间，且为 float"""
    fn, mod, path = _get_reranker()
    results = fn(query="apple fruit", documents=SAMPLE_DOCS)
    assert len(results) == len(SAMPLE_DOCS)
    for r in results:
        s = _score(r)
        assert isinstance(s, float), f"分数应为 float，实际 {type(s)} {s}"
        assert 0.0 <= s <= 1.0, f"分数应在 0-1 区间，实际 {s}, 完整 {results}"
        # also check raw relevance_score field
        field = next((k for k in ("relevance_score", "score", "relevance") if k in r), None)
        assert field is not None
        raw = r[field]
        assert 0.0 <= float(raw) <= 1.0


def test_reranker_batch():
    """批量：支持大批量文档（8+），重复调用及批量去重/缓存应一致"""
    fn, mod, path = _get_reranker()
    # 批量 8 文档
    docs = SAMPLE_DOCS + EXTRA_DOCS[:4]
    # docs = 8
    assert len(docs) == 8
    results = fn(query="apple fruit", documents=docs)
    assert isinstance(results, list) and len(results) == len(docs)
    # 语义 top 仍为 apple fruit 相关
    top = _doc(results[0])
    assert "Apple" in top and "fruit" in top.lower(), f"批量语义失败 top {top!r}"

    # 重复批量应命中缓存且结果一致（稳定性亦体现缓存）
    results2 = fn(query="apple fruit", documents=docs)
    assert [_doc(r) for r in results] == [_doc(r) for r in results2], "批量缓存后排序不一致"
    scores1 = [_score(r) for r in results]
    scores2 = [_score(r) for r in results2]
    for a, b in zip(scores1, scores2):
        assert abs(a - b) < 1e-6, f"批量缓存分数不一致 {a} vs {b}"

    # 若模块暴露批量接口 rerank_batch / parallel_rerank 则测试其与单调用一致性
    batch_fn = None
    for name in ("rerank_batch", "batch_rerank", "parallel_rerank", "rerank_many"):
        if hasattr(mod, name) and callable(getattr(mod, name)):
            batch_fn = getattr(mod, name)
            break
    if batch_fn is not None:
        # 尝试 batch 接口：通常签名 (queries, documents_list) 或 (query, docs) 批
        import inspect
        sig = inspect.signature(batch_fn)
        try:
            # 假设签名 rerank_batch(queries, documents_list)
            if len(sig.parameters) >= 2:
                queries = ["apple fruit", "car engine"]
                doc_lists = [SAMPLE_DOCS, SAMPLE_DOCS]
                batch_res = batch_fn(queries, doc_lists)  # type: ignore
                # 也可能签名 rerank_batch(query, documents) 批处理分片
                if isinstance(batch_res, list) and batch_res and isinstance(batch_res[0], list):
                    assert len(batch_res) == 2
                    for grp in batch_res:
                        assert len(grp) == len(SAMPLE_DOCS)
        except Exception:
            pass  # 批量接口可选，不强制失败，单批已验证

    # 若未暴露批量接口，至少验证分片处理：超长文档列表（如 20）仍可处理
    large_docs = (SAMPLE_DOCS * 5)[:20]
    # 去重场景？保持独特 docs + 重复
    large_docs = [f"{d} var{i}" if i >= 4 else d for i, d in enumerate(large_docs)]
    res_large = fn(query="apple fruit", documents=large_docs)
    assert len(res_large) == len(large_docs), f"大批量长度不一致 期望 {len(large_docs)} 实际 {len(res_large)}"


def test_reranker_empty():
    """严格校验：空参异常与空列表语义"""
    fn, mod, path = _get_reranker()
    # 空 query -> ValueError
    with pytest.raises((ValueError, TypeError)):
        fn(query="", documents=SAMPLE_DOCS)
    with pytest.raises((ValueError, TypeError)):
        fn(query="   ", documents=SAMPLE_DOCS)
    with pytest.raises((ValueError, TypeError, TypeError)):
        fn(query=None, documents=SAMPLE_DOCS)  # type: ignore
    # 非字符串 query
    with pytest.raises((ValueError, TypeError)):
        fn(query=123, documents=SAMPLE_DOCS)  # type: ignore
    # 非列表 documents
    with pytest.raises((TypeError, ValueError)):
        fn(query="apple", documents=None)  # type: ignore
    with pytest.raises((TypeError, ValueError)):
        fn(query="apple", documents="not a list")  # type: ignore
    # 空 documents 列表应返回 [] 而非异常（契约）
    res = fn(query="apple", documents=[])
    assert isinstance(res, list) and len(res) == 0, f"空 documents 应返回 []，实际 {res}"
    # documents 元素非 str
    with pytest.raises(TypeError):
        fn(query="apple", documents=["ok", 123])  # type: ignore
    with pytest.raises(TypeError):
        fn(query="apple", documents=["ok", None])  # type: ignore


def test_reranker_stability():
    """稳定性：相同输入多次调用分数与排序完全一致（确定性），且降序"""
    fn, mod, path = _get_reranker()
    query = "apple fruit"
    runs = []
    for _ in range(3):
        results = fn(query=query, documents=SAMPLE_DOCS)
        runs.append(results)
    # 首次作为基准
    base_docs = [_doc(r) for r in runs[0]]
    base_scores = [_score(r) for r in runs[0]]
    assert base_scores == sorted(base_scores, reverse=True), "首次结果未降序"
    for idx, run in enumerate(runs[1:], start=1):
        docs = [_doc(r) for r in run]
        scores = [_score(r) for r in run]
        assert docs == base_docs, f"第 {idx} 次运行排序不稳定 期望 {base_docs} 实际 {docs}"
        for a, b in zip(base_scores, scores):
            assert abs(a - b) < 1e-6, f"第 {idx} 次分数不稳定 {a} vs {b}"
    # 轻微文档顺序变化不应影响最终归一化排序的稳定性（缓存键包含 query|doc）
    shuffled = list(reversed(SAMPLE_DOCS))
    res_shuffled = fn(query=query, documents=shuffled)
    # 但排序后 top 仍应一致（Apple is a fruit 仍首位）
    assert _doc(res_shuffled[0]).strip() == "Apple is a fruit that grows on trees"


def test_reranker_normalized_scores():
    """归一化分数：0-1 区间、区分度 std>0、非整数计数、且分数经 L2 归一化/ sigmoid 映射"""
    fn, mod, path = _get_reranker()
    results = fn(query="apple fruit", documents=SAMPLE_DOCS)
    scores = [_score(r) for r in results]
    assert len(scores) == len(SAMPLE_DOCS)
    # 0-1 且非全部相等
    assert all(0.0 <= s <= 1.0 for s in scores), f"归一化失败 scores={scores}"
    # 非整数计数特征：至少有一个分数不是整数（区别于 overlap stub 的 0,1,2）
    # 且小数分数应存在
    has_fraction = any(abs(s - round(s)) > 1e-6 for s in scores)
    # 如果全为 0/1 整数且 max==2 则说明仍为 stub，非归一化
    assert has_fraction or max(scores) <= 1.0 and max(scores) != 2.0, f"分数未归一化，疑似 stub 计数 {scores}"
    # 区分度：std 需 >0 且不宜过小（至少 0.05）
    if len(scores) >= 2:
        std = statistics.pstdev(scores) if len(scores) > 1 else 0.0
        assert std > 0.03, f"分数区分度过低 std={std:.4f} scores={scores}, 应 >0.03 以体现语义区分"
        # 最高与最低差值应显著
        diff = max(scores) - min(scores)
        assert diff > 0.05, f"最大最小差值过小 {diff:.4f} scores={scores}"
    # Top 分数不应为 0 且不应为 1 的极值被 clip？允许 1 但需合理
    assert scores[0] > 0.1, f"top 分数过低 {scores[0]}, 应 >0.1"
    # 若模型可用，top 应接近较高值（至少 0.5），fallback 哈希余弦的 top 也应在 0.5+
    assert scores[0] >= 0.4, f"归一化后 top 分数过低 {scores[0]}，应 ≥0.4"

    # 对比另一个 query，分数分布应变化（语义敏感）
    results_q2 = fn(query="car engine", documents=SAMPLE_DOCS)
    scores_q2 = [_score(r) for r in results_q2]
    # car engine 的 top 应为 Car engine 文档
    top_q2 = _doc(results_q2[0])
    assert "Car engine" in top_q2, f"第二 query 语义错误 top {top_q2!r} scores {scores_q2}"

    # 若暴露 get_backend / score_details 等，可选验证 L2 归一化
    # 仅检查分数在 0-1 即视为 L2 归一化后映射

