"""本地 Reranker 服务，替代 jina sort_by_relevance / rerank

- 优先 sentence-transformers CrossEncoder `cross-encoder/ms-marco-MiniLM-L6-v2`（~80MB，CPU 可跑）若本地有；否则用 embeddings 余弦相似度 fallback，L2 归一化且分数映射到 0-1
- 支持 rerank(query, documents) -> list[dict]{document, relevance_score} 降序，保留文档集合
- 支持批量、缓存（sha256(query|doc) -> score）
- 严格校验空参
"""
import hashlib
import logging
import math
import pathlib
import re
import threading
from typing import List, Dict

import numpy as np

logger = logging.getLogger(__name__)

CACHE_DIR = pathlib.Path("/tmp/opencode/jina-local")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_MODEL_ID = "cross-encoder/ms-marco-MiniLM-L6-v2"
_model = None
_backend: str | None = None  # "cross" or "embed"
_lock = threading.Lock()
_score_cache: dict[str, float] = {}
_cache_lock = threading.Lock()


def _sigmoid(x: float) -> float:
    try:
        # clip for overflow
        if x < -15:
            return 0.0
        if x > 15:
            return 1.0
        return 1.0 / (1.0 + math.exp(-x))
    except Exception:
        return 0.5


def _cache_key(query: str, doc: str) -> str:
    raw = f"{query}|||{doc}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_path_for_key(key: str) -> pathlib.Path:
    return CACHE_DIR / f"rerank-{key}.json"


def _get_cached(key: str) -> float | None:
    with _cache_lock:
        if key in _score_cache:
            return _score_cache[key]
    # try disk cache
    p = _cache_path_for_key(key)
    if p.exists():
        try:
            txt = p.read_text(encoding="utf-8").strip()
            val = float(txt)
            # also populate memory
            with _cache_lock:
                _score_cache[key] = val
            return val
        except Exception as e:
            logger.debug("rerank disk cache read fail %s: %s", key[:8], e)
    return None


def _set_cached(key: str, score: float) -> None:
    with _cache_lock:
        _score_cache[key] = score
    # disk write best effort
    p = _cache_path_for_key(key)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(score), encoding="utf-8")
    except Exception as e:
        logger.debug("rerank cache write fail %s: %s", key[:8], e)


def _init_backend() -> str:
    global _model, _backend
    if _backend is not None:
        return _backend
    with _lock:
        if _backend is not None:
            return _backend
        # try CrossEncoder local_files_only
        try:
            from sentence_transformers import CrossEncoder  # type: ignore

            # 优先离线加载本地缓存
            try:
                m = CrossEncoder(_MODEL_ID, device="cpu", local_files_only=True, trust_remote_code=True)
                _model = m
                _backend = "cross"
                logger.info("Reranker backend: CrossEncoder %s (local)", _MODEL_ID)
                return _backend
            except Exception as e:
                logger.debug("CrossEncoder local load fail %s: %s", _MODEL_ID, e)
                # 若允许下载则尝试在线加载（默认不下载，避免阻塞）
                import os

                if os.getenv("JINA_LOCAL_ALLOW_DOWNLOAD", "0") == "1":
                    try:
                        m2 = CrossEncoder(_MODEL_ID, device="cpu", trust_remote_code=True)
                        _model = m2
                        _backend = "cross"
                        logger.info("Reranker backend: CrossEncoder %s (downloaded)", _MODEL_ID)
                        return _backend
                    except Exception as e2:
                        logger.debug("CrossEncoder download fail: %s", e2)
        except ImportError as e:
            logger.debug("sentence_transformers not installed: %s", e)
        except Exception as e:
            logger.debug("reranker init error: %s", e)
        # fallback to embeddings
        _backend = "embed"
        _model = None
        logger.info("Reranker backend: embeddings cosine fallback (L2 normalized, mapped 0-1)")
        return _backend


def _validate(query, documents):
    if query is None:
        raise TypeError("query 必须为非空字符串，不能为 None")
    if not isinstance(query, str):
        raise TypeError("query 必须为 str")
    if not query.strip():
        raise ValueError("query 必须为非空字符串")
    if documents is None:
        raise TypeError("documents 必须为 list[str]，不能为 None")
    if not isinstance(documents, list):
        raise TypeError("documents 必须为 list[str]")
    # empty list is allowed -> return [] downstream
    for d in documents:
        if not isinstance(d, str):
            raise TypeError("documents 元素必须为 str")
        # 严格校验：不允许空字符串作为文档内容（可选，满足 spec）
        # 但空文档可视为 ValueError? 任务要求严格校验空参，这里对空串抛 ValueError
        if d is not None and isinstance(d, str) and not d.strip():
            # 若文档为空字符串，视为无效输入，抛 ValueError
            # 为兼容空列表的语义，空串单独报错
            raise ValueError("documents 元素不能为空字符串")
    return query.strip(), documents


def _embed_cosine_scores(query: str, docs: List[str]) -> List[float]:
    """Fallback: embeddings 余弦，L2 归一化且映射到 0-1"""
    # 动态导入 embeddings 避免循环
    try:
        from .embeddings import embed as _embed  # type: ignore
    except ImportError:
        try:
            from embeddings import embed as _embed  # type: ignore
        except ImportError:
            import importlib.util
            import pathlib as _pl

            # fallback load via file
            candidates = [
                pathlib.Path(__file__).parent / "embeddings.py",
                pathlib.Path("/home/cc/jina-local/mcp-gateway/src/embeddings.py"),
            ]
            mod = None
            for p in candidates:
                if p.exists():
                    spec = importlib.util.spec_from_file_location("embeddings_fallback", p)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)  # type: ignore
                    break
            if mod is None or not hasattr(mod, "embed"):
                raise RuntimeError("embeddings 模块未加载")
            _embed = mod.embed  # type: ignore

    # batch embed query+docs
    texts = [query] + docs
    vecs = _embed(texts)  # list[list[float]] L2 normalized
    # ensure numpy
    arrs = [np.array(v, dtype=np.float32) for v in vecs]
    # double-check L2 normalize (embed already normalized, but ensure)
    for i in range(len(arrs)):
        n = np.linalg.norm(arrs[i])
        if n > 0 and abs(n - 1.0) > 1e-4:
            arrs[i] = arrs[i] / n
    qv = arrs[0]
    scores: List[float] = []
    for dv in arrs[1:]:
        cos = float(np.dot(qv, dv))
        # clip cosine to [-1,1]
        if cos > 1.0:
            cos = 1.0
        if cos < -1.0:
            cos = -1.0
        # 映射到 0-1：若 cos 已在 0-1（hash 情况）直接保留以保持区分度；
        # 若存在负值则用 (cos+1)/2 映射；统一处理为 max(0, cos) 再保持？
        # 为满足“映射到 0-1”且最大区分度，采用：
        # - 若 cos >=0 : score = cos (已 0-1)
        # - 若 cos <0 : score = (cos+1)/2 (映射负值到 0-0.5)
        # 这样 hash (non-negative) 保留 raw 0.5 diff，HF 负值也映射合理
        if cos >= 0:
            score = cos
        else:
            score = (cos + 1.0) / 2.0
        # clamp
        if score < 0.0:
            score = 0.0
        if score > 1.0:
            score = 1.0
        scores.append(float(score))
    return scores


def _cross_scores(query: str, docs: List[str]) -> List[float]:
    assert _model is not None
    pairs = [(query, d) for d in docs]
    try:
        # CrossEncoder.predict returns logits
        raw = _model.predict(pairs, convert_to_numpy=True, show_progress_bar=False)  # type: ignore
        # ensure array
        if isinstance(raw, np.ndarray):
            raws = raw.tolist()
        elif isinstance(raw, list):
            raws = raw
        else:
            raws = list(raw)
        scores: List[float] = []
        for v in raws:
            try:
                fv = float(v)
            except Exception:
                fv = 0.0
            # sigmoid to 0-1
            s = _sigmoid(fv)
            # clamp
            if s < 0:
                s = 0.0
            if s > 1:
                s = 1.0
            scores.append(float(s))
        return scores
    except Exception as e:
        logger.debug("CrossEncoder predict fail, fallback to embed: %s", e)
        return _embed_cosine_scores(query, docs)


def rerank(query: str, documents: List[str]) -> List[Dict]:
    """主入口：语义 rerank，分数降序，保留文档集合，带缓存"""
    query, documents = _validate(query, documents)
    if not documents:
        return []
    backend = _init_backend()

    # step 1: cache lookup
    keys = [_cache_key(query, d) for d in documents]
    indices_uncached: List[int] = []
    docs_uncached: List[str] = []
    cached_scores: dict[int, float] = {}
    for idx, (doc, key) in enumerate(zip(documents, keys)):
        v = _get_cached(key)
        if v is not None:
            cached_scores[idx] = v
        else:
            indices_uncached.append(idx)
            docs_uncached.append(doc)

    # step 2: compute uncached
    if docs_uncached:
        if backend == "cross" and _model is not None:
            computed = _cross_scores(query, docs_uncached)
        else:
            computed = _embed_cosine_scores(query, docs_uncached)
        for idx, sc in zip(indices_uncached, computed):
            key = keys[idx]
            _set_cached(key, float(sc))
            cached_scores[idx] = float(sc)

    # step 3: assemble
    scored: List[Dict] = []
    for idx, doc in enumerate(documents):
        sc = cached_scores.get(idx, 0.0)
        # ensure float 0-1
        sc = float(sc)
        if sc < 0:
            sc = 0.0
        if sc > 1:
            sc = 1.0
        scored.append({"document": doc, "relevance_score": float(sc), "_idx": idx})

    # sort descending by score, then ascending by original index for stability
    scored.sort(key=lambda x: (-x["relevance_score"], x["_idx"]))
    for item in scored:
        item.pop("_idx", None)
        item["relevance_score"] = float(item["relevance_score"])
    return scored


def sort_by_relevance(query: str, documents: List[str]) -> List[Dict]:
    """兼容 jina sort_by_relevance 别名"""
    return rerank(query, documents)


def rerank_batch(queries: List[str], documents_list: List[List[str]]) -> List[List[Dict]]:
    """批量 rerank：queries 与 documents_list 一一对应"""
    if not isinstance(queries, list):
        raise TypeError("queries 必须为 list[str]")
    if not isinstance(documents_list, list):
        raise TypeError("documents_list 必须为 list[list[str]]")
    if len(queries) != len(documents_list):
        raise ValueError("queries 与 documents_list 长度必须一致")
    out: List[List[Dict]] = []
    for q, docs in zip(queries, documents_list):
        out.append(rerank(q, docs))
    return out


# 便捷别名
reranker = rerank

def get_backend() -> str:
    return _init_backend()

def clear_cache():
    with _cache_lock:
        _score_cache.clear()
    # also clear disk
    for p in CACHE_DIR.glob("rerank-*.json"):
        try:
            p.unlink()
        except Exception:
            pass

