"""本地 Reranker 服务，替代 jina sort_by_relevance / rerank

- 优先 sentence-transformers CrossEncoder `cross-encoder/ms-marco-MiniLM-L6-v2`（~80MB，CPU 可跑）若本地有；否则用 embeddings 余弦相似度 fallback，L2 归一化且分数映射到 0-1
- 支持 GPU 自动检测 cuda + float16 量化，显存预算日志
- 支持 rerank(query, documents) -> list[dict]{document, relevance_score} 降序，保留文档集合
- 支持批量、缓存（sha256(query|doc) -> score），max_batch_tokens 分片
- 严格校验空参
"""
import hashlib
import json
import logging
import math
import os
import pathlib
import threading
import time
from typing import List, Dict

import weakref

import numpy as np

logger = logging.getLogger(__name__)

CACHE_DIR = pathlib.Path("/tmp/opencode/jina-local")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
GPU_STATS_PATH = CACHE_DIR / "gpu-stats.json"

_MODEL_ID = "cross-encoder/ms-marco-MiniLM-L6-v2"
_model = None
_backend: str | None = None  # "cross" or "embed"
_device: str | None = None
_lock = threading.Lock()
_score_cache: dict[str, float] = {}
_cache_lock = threading.Lock()

_MAX_BATCH_TOKENS = int(os.getenv("JINA_LOCAL_MAX_BATCH_TOKENS", "16384"))

# 按需加载：默认开启，减少常驻内存 50%
_JINA_LAZY = os.getenv("JINA_LOCAL_LAZY_LOAD", "1").strip().lower() not in ("0", "false", "no", "off")
_IDLE_TIMEOUT = int(os.getenv("JINA_LOCAL_IDLE_TIMEOUT", "1800"))
_last_used: float | None = None
_model_ref: weakref.ReferenceType | None = None


def _touch():
    global _last_used
    _last_used = time.monotonic()


def _maybe_release_idle():
    global _model, _backend, _model_ref
    if not _JINA_LAZY or _model is None or _last_used is None:
        return False
    if time.monotonic() - _last_used < _IDLE_TIMEOUT:
        return False
    with _lock:
        if _model is None or _last_used is None:
            return False
        if time.monotonic() - _last_used < _IDLE_TIMEOUT:
            return False
        logger.info("Reranker idle %.0fs > %s releasing %s", time.monotonic() - _last_used, _IDLE_TIMEOUT, _MODEL_ID)
        try:
            try:
                _model_ref = weakref.ref(_model) if _model is not None else None
            except Exception:
                _model_ref = None
            _model = None
            _backend = None
            try:
                import torch  # type: ignore

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            try:
                import gc

                gc.collect()
            except Exception:
                pass
            _write_gpu_stats("reranker_released_idle", {"idle_timeout": _IDLE_TIMEOUT})
        except Exception as e:
            logger.debug("reranker release idle fail: %s", e)
        return True


def _release_backend():
    global _model, _backend, _model_ref
    with _lock:
        _model_ref = weakref.ref(_model) if _model is not None else None
        _model = None
        _backend = None
        try:
            import torch  # type: ignore

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
    logger.info("Reranker backend released manually")


def _detect_device() -> str:
    env_dev = os.getenv("JINA_LOCAL_RERANKER_DEVICE", "").strip()
    if not env_dev:
        env_dev = os.getenv("JINA_LOCAL_EMBEDDINGS_DEVICE", "").strip()
    if env_dev:
        return env_dev
    use_gpu = os.getenv("JINA_LOCAL_USE_GPU", "1").strip().lower()
    if use_gpu in ("0", "false", "no", "off"):
        return "cpu"
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            return "cuda"
    except Exception as e:
        logger.debug("torch cuda check fail: %s", e)
    return "cpu"


def _get_device() -> str:
    global _device
    if _device is not None:
        return _device
    _device = _detect_device()
    return _device


def _gpu_memory_mb() -> dict:
    info = {"allocated_mb": 0, "reserved_mb": 0, "device": _get_device(), "cuda_available": False}
    try:
        import torch  # type: ignore

        info["cuda_available"] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            try:
                info["allocated_mb"] = round(torch.cuda.memory_allocated() / 1024 / 1024, 2)
            except Exception:
                pass
            try:
                info["reserved_mb"] = round(torch.cuda.memory_reserved() / 1024 / 1024, 2)
            except Exception:
                pass
            try:
                info["device_name"] = torch.cuda.get_device_name(0)
            except Exception:
                pass
    except Exception:
        pass
    return info


def _write_gpu_stats(stage: str, extra: dict | None = None):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        mem = _gpu_memory_mb()
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "stage": stage,
            "device": _get_device(),
            "backend": _backend,
            "model": _MODEL_ID if _backend == "cross" else "embed_fallback",
            "memory": mem,
        }
        if extra:
            entry.update(extra)
        data = {}
        if GPU_STATS_PATH.exists():
            try:
                data = json.loads(GPU_STATS_PATH.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except Exception:
                data = {}
        if "reranker" not in data or not isinstance(data.get("reranker"), dict):
            data["reranker"] = {}
        hist = data.get("history", [])
        if not isinstance(hist, list):
            hist = []
        hist.append({"module": "reranker", **entry})
        if len(hist) > 50:
            hist = hist[-50:]
        data["history"] = hist
        data["reranker"] = entry
        data["last_update"] = entry["timestamp"]
        GPU_STATS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("GPU stats [%s] device=%s allocated=%.1fMB backend=%s", stage, entry["device"], mem.get("allocated_mb", 0), _backend)
        print(f"[reranker] GPU stats {stage}: device={entry['device']} allocated={mem.get('allocated_mb',0)}MB backend={_backend}")
    except Exception as e:
        logger.debug("write gpu stats fail: %s", e)


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / 4))


def _batch_by_tokens_pairs(query: str, docs: List[str], max_tokens: int | None = None) -> List[List[str]]:
    if max_tokens is None:
        try:
            max_tokens = int(os.getenv("JINA_LOCAL_MAX_BATCH_TOKENS", str(_MAX_BATCH_TOKENS)))
        except Exception:
            max_tokens = _MAX_BATCH_TOKENS
    if max_tokens <= 0:
        return [docs]
    batches: List[List[str]] = []
    cur: List[str] = []
    cur_tokens = 0
    q_tok = _estimate_tokens(query)
    for d in docs:
        tok = q_tok + _estimate_tokens(d) + 2
        if tok > max_tokens:
            if cur:
                batches.append(cur)
                cur = []
                cur_tokens = 0
            batches.append([d])
            continue
        if cur_tokens + tok > max_tokens and cur:
            batches.append(cur)
            cur = [d]
            cur_tokens = tok
        else:
            cur.append(d)
            cur_tokens += tok
    if cur:
        batches.append(cur)
    return batches


def _sigmoid(x: float) -> float:
    try:
        if x < -15:
            return 0.0
        if x > 15:
            return 1.0
        return 1.0 / (1.0 + math.exp(-x))
    except Exception:
        return 0.5


def _cache_key(query: str, doc: str) -> str:
    raw = f"{_backend or 'unknown'}|||{_MODEL_ID}|||{query}|||{doc}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_path_for_key(key: str) -> pathlib.Path:
    return CACHE_DIR / f"rerank-{key}.json"


def _get_cached(key: str) -> float | None:
    with _cache_lock:
        if key in _score_cache:
            return _score_cache[key]
    p = _cache_path_for_key(key)
    if p.exists():
        try:
            txt = p.read_text(encoding="utf-8").strip()
            val = float(txt)
            with _cache_lock:
                _score_cache[key] = val
            return val
        except Exception as e:
            logger.debug("rerank disk cache read fail %s: %s", key[:8], e)
    return None


def _set_cached(key: str, score: float) -> None:
    with _cache_lock:
        _score_cache[key] = score
    p = _cache_path_for_key(key)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(score), encoding="utf-8")
    except Exception as e:
        logger.debug("rerank cache write fail %s: %s", key[:8], e)




def _tei_url() -> str:
    return os.getenv("JINA_LOCAL_RERANKER_URL", "http://127.0.0.1:3002/rerank")


def _tei_rerank(query: str, documents: List[str]) -> List[float] | None:
    try:
        import requests
        response = requests.post(_tei_url(), json={"query": query, "texts": documents}, timeout=float(os.getenv("JINA_LOCAL_TEI_TIMEOUT", "10")))
        response.raise_for_status()
        payload = response.json()
        scores = [0.0] * len(documents)
        for item in payload:
            scores[int(item["index"])] = max(0.0, min(1.0, float(item["score"])))
        return scores
    except Exception as exc:
        logger.warning("TEI reranker unavailable at %s: %s", _tei_url(), exc)
        return None

def _init_backend() -> str:
    global _model, _backend, _device, _model_ref
    if _backend is not None:
        _maybe_release_idle()
        if _backend is not None:
            _touch()
            return _backend
    with _lock:
        if _backend is not None:
            _touch()
            return _backend
        device = _get_device()
        tei_probe = _tei_rerank("__jina_local_healthcheck__", ["healthcheck"])
        if tei_probe is not None:
            _backend = "tei"
            _touch()
            _write_gpu_stats("reranker_tei", {"device": "remote-gpu", "url": _tei_url()})
            return _backend
        try:
            mem_before = _gpu_memory_mb()
            logger.info("Reranker init start device=%s mem_before=%.1fMB", device, mem_before.get("allocated_mb", 0))
            print(f"[reranker] init start device={device} mem_before={mem_before.get('allocated_mb',0)}MB")
        except Exception:
            pass
        try:
            from sentence_transformers import CrossEncoder  # type: ignore

            try:
                kwargs = dict(device=device, local_files_only=True, trust_remote_code=True)
                # attempt fp16 for cuda
                use_fp16 = device.startswith("cuda")
                if use_fp16:
                    try:
                        import torch  # type: ignore

                        kwargs["model_kwargs"] = {"torch_dtype": torch.float16}  # type: ignore
                    except Exception:
                        pass
                m = CrossEncoder(_MODEL_ID, **kwargs)  # type: ignore
                if use_fp16:
                    try:
                        # CrossEncoder wraps model; try half() on underlying model
                        if hasattr(m, "model") and hasattr(m.model, "half"):
                            m.model.half()  # type: ignore
                        elif hasattr(m, "half"):
                            m.half()  # type: ignore
                        logger.info("Reranker half() applied for %s on %s", _MODEL_ID, device)
                    except Exception as e:
                        logger.debug("reranker half fail: %s", e)
                _model = m
                _backend = "cross"
                _touch()
                try:
                    _model_ref = weakref.ref(m)
                except Exception:
                    _model_ref = None
                logger.info("Reranker backend: CrossEncoder %s (local) device=%s", _MODEL_ID, device)
                _write_gpu_stats("reranker_loaded", {"model": _MODEL_ID, "device": device})
                try:
                    mem_after = _gpu_memory_mb()
                    logger.info("Reranker mem after load allocated=%.1fMB", mem_after.get("allocated_mb", 0))
                    print(f"[reranker] loaded {_MODEL_ID} device={device} mem_after={mem_after.get('allocated_mb',0)}MB")
                except Exception:
                    pass
                return _backend
            except Exception as e:
                logger.debug("CrossEncoder local load fail %s on %s: %s", _MODEL_ID, device, e)
                import os

                if os.getenv("JINA_LOCAL_ALLOW_DOWNLOAD", "0") == "1":
                    try:
                        m2 = CrossEncoder(_MODEL_ID, device=device, trust_remote_code=True)  # type: ignore
                        if device.startswith("cuda"):
                            try:
                                if hasattr(m2, "model") and hasattr(m2.model, "half"):
                                    m2.model.half()  # type: ignore
                            except Exception:
                                pass
                        _model = m2
                        _backend = "cross"
                        _touch()
                        try:
                            _model_ref = weakref.ref(m2)
                        except Exception:
                            _model_ref = None
                        logger.info("Reranker backend: CrossEncoder %s (downloaded) device=%s", _MODEL_ID, device)
                        _write_gpu_stats("reranker_downloaded", {"model": _MODEL_ID, "device": device})
                        return _backend
                    except Exception as e2:
                        logger.debug("CrossEncoder download fail: %s", e2)
        except ImportError as e:
            logger.debug("sentence_transformers not installed: %s", e)
        except Exception as e:
            logger.debug("reranker init error: %s", e)
        _backend = "embed"
        _model = None
        _touch()
        logger.info("Reranker backend: embeddings cosine fallback (L2 normalized, mapped 0-1) device=%s", device)
        _write_gpu_stats("reranker_embed_fallback", {"device": device})
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
    for d in documents:
        if not isinstance(d, str):
            raise TypeError("documents 元素必须为 str")
        if d is not None and isinstance(d, str) and not d.strip():
            raise ValueError("documents 元素不能为空字符串")
    return query.strip(), documents


def _embed_cosine_scores(query: str, docs: List[str]) -> List[float]:
    try:
        from .embeddings import embed as _embed  # type: ignore
    except ImportError:
        try:
            from embeddings import embed as _embed  # type: ignore
        except ImportError:
            import importlib.util
            import pathlib as _pl

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

    texts = [query] + docs
    vecs = _embed(texts)
    arrs = [np.array(v, dtype=np.float32) for v in vecs]
    for i in range(len(arrs)):
        n = np.linalg.norm(arrs[i])
        if n > 0 and abs(n - 1.0) > 1e-4:
            arrs[i] = arrs[i] / n
    qv = arrs[0]
    scores: List[float] = []
    for dv in arrs[1:]:
        cos = float(np.dot(qv, dv))
        if cos > 1.0:
            cos = 1.0
        if cos < -1.0:
            cos = -1.0
        if cos >= 0:
            score = cos
        else:
            score = (cos + 1.0) / 2.0
        if score < 0.0:
            score = 0.0
        if score > 1.0:
            score = 1.0
        scores.append(float(score))
    return scores


def _cross_scores(query: str, docs: List[str]) -> List[float]:
    assert _model is not None
    # batch slicing by max_batch_tokens
    batches = _batch_by_tokens_pairs(query, docs)
    all_scores: List[float] = []
    for batch in batches:
        pairs = [(query, d) for d in batch]
        try:
            raw = _model.predict(pairs, convert_to_numpy=True, show_progress_bar=False)  # type: ignore
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
                s = _sigmoid(fv)
                if s < 0:
                    s = 0.0
                if s > 1:
                    s = 1.0
                scores.append(float(s))
            all_scores.extend(scores)
        except Exception as e:
            logger.debug("CrossEncoder predict fail batch, fallback to embed: %s", e)
            # fallback for this batch
            fallback = _embed_cosine_scores(query, batch)
            all_scores.extend(fallback)
    return all_scores


def rerank(query: str, documents: List[str]) -> List[Dict]:
    query, documents = _validate(query, documents)
    if not documents:
        return []
    backend = _init_backend()

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

    if docs_uncached:
        if backend == "tei":
            computed = _tei_rerank(query, docs_uncached)
            if computed is None:
                computed = _embed_cosine_scores(query, docs_uncached)
        elif backend == "cross" and _model is not None:
            computed = _cross_scores(query, docs_uncached)
        else:
            # also batch slicing for embed fallback (via _batch_by_tokens_pairs -> embed batch slicing anyway)
            # but direct call _embed_cosine_scores already batches via embed's slicing
            computed = _embed_cosine_scores(query, docs_uncached)
        for idx, sc in zip(indices_uncached, computed):
            key = keys[idx]
            _set_cached(key, float(sc))
            cached_scores[idx] = float(sc)

    scored: List[Dict] = []
    for idx, doc in enumerate(documents):
        sc = cached_scores.get(idx, 0.0)
        sc = float(sc)
        if sc < 0:
            sc = 0.0
        if sc > 1:
            sc = 1.0
        scored.append({"document": doc, "relevance_score": float(sc), "_idx": idx})

    scored.sort(key=lambda x: (-x["relevance_score"], x["_idx"]))
    for item in scored:
        item.pop("_idx", None)
        item["relevance_score"] = float(item["relevance_score"])
    return scored


def sort_by_relevance(query: str, documents: List[str]) -> List[Dict]:
    return rerank(query, documents)


def rerank_batch(queries: List[str], documents_list: List[List[str]]) -> List[List[Dict]]:
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


reranker = rerank

def get_backend() -> str:
    return _init_backend()

def get_device() -> str:
    return _get_device()

def clear_cache():
    with _cache_lock:
        _score_cache.clear()
    for p in CACHE_DIR.glob("rerank-*.json"):
        try:
            p.unlink()
        except Exception:
            pass

def get_gpu_stats() -> dict:
    try:
        if GPU_STATS_PATH.exists():
            return json.loads(GPU_STATS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"memory": _gpu_memory_mb(), "device": _get_device(), "backend": _backend}


def release_model():
    _release_backend()
    return {"released": True, "backend": _backend, "lazy": _JINA_LAZY, "idle_timeout": _IDLE_TIMEOUT}


if not _JINA_LAZY:
    try:
        _init_backend()
    except Exception as e:
        logger.debug("eager init fail: %s", e)
