"""本地 Embeddings 服务，替代 jina embeddings
- 优先加载 sentence-transformers 本地模型 BAAI/bge-m3 或 all-MiniLM-L6-v2
- 支持 GPU 自动检测 (cuda:0) + float16 量化，显存预算日志
- 无模型/无依赖则 fallback 到 哈希 TF + L2 归一化 (保证离线可用、语义区分度、维度一致)
- 支持 embed(texts) 与 embed_one(text)，批量、缓存、严格校验、max_batch_tokens 分片
"""
import hashlib
import json
import logging
import os
import pathlib
import re
import threading
import time

import weakref

import numpy as np

logger = logging.getLogger(__name__)

CACHE_DIR = pathlib.Path("/tmp/opencode/jina-local")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
GPU_STATS_PATH = CACHE_DIR / "gpu-stats.json"

_DIM = 384
_model = None
_model_name: str | None = None
_backend: str | None = None  # "hf" or "hash"
_device: str | None = None  # "cuda", "cuda:0", "cpu"
_lock = threading.Lock()

_CANDIDATE_MODELS = [
    "BAAI/bge-m3",
    "sentence-transformers/all-MiniLM-L6-v2",
]

_MAX_BATCH_TOKENS = int(os.getenv("JINA_LOCAL_MAX_BATCH_TOKENS", "16384"))

# 按需加载：默认开启，减少常驻内存 50%（模型仅首次 embed 时加载，闲置超时后释放）
_JINA_LAZY = os.getenv("JINA_LOCAL_LAZY_LOAD", "1").strip().lower() not in ("0", "false", "no", "off")
_IDLE_TIMEOUT = int(os.getenv("JINA_LOCAL_IDLE_TIMEOUT", "1800"))
_last_used: float | None = None
_model_ref: weakref.ReferenceType | None = None


def _touch():
    global _last_used
    _last_used = time.monotonic()


def _maybe_release_idle():
    global _model, _model_name, _backend, _DIM, _model_ref
    if not _JINA_LAZY or _model is None or _last_used is None:
        return False
    if time.monotonic() - _last_used < _IDLE_TIMEOUT:
        return False
    with _lock:
        if _model is None or _last_used is None:
            return False
        if time.monotonic() - _last_used < _IDLE_TIMEOUT:
            return False
        logger.info("Embeddings idle %.0fs > %s, releasing model %s (weakref)", time.monotonic() - _last_used, _IDLE_TIMEOUT, _model_name)
        try:
            # release via weakref optional: drop strong ref, keep weakref for inspection
            try:
                _model_ref = weakref.ref(_model) if _model is not None else None
            except Exception:
                _model_ref = None
            _model = None
            _backend = None
            # try free GPU cache
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
            _write_gpu_stats("embeddings_released_idle", {"idle_timeout": _IDLE_TIMEOUT})
        except Exception as e:
            logger.debug("release idle fail: %s", e)
        return True


def _release_backend():
    global _model, _backend, _model_name, _model_ref
    with _lock:
        _model_ref = weakref.ref(_model) if _model is not None else None
        _model = None
        _backend = None
        _model_name = None
        try:
            import torch  # type: ignore
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
    logger.info("Embeddings backend released manually")


def _detect_device() -> str:
    # explicit device override
    env_dev = os.getenv("JINA_LOCAL_EMBEDDINGS_DEVICE", "").strip()
    if env_dev:
        return env_dev
    # global gpu switch
    use_gpu = os.getenv("JINA_LOCAL_USE_GPU", "1").strip().lower()
    if use_gpu in ("0", "false", "no", "off"):
        return "cpu"
    # auto detect torch cuda
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            return "cuda"
            # alternative "cuda:0" also valid; SentenceTransformer accepts "cuda" / "cuda:0"
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
            "model": _model_name,
            "memory": mem,
        }
        if extra:
            entry.update(extra)
        # merge with existing
        data = {}
        if GPU_STATS_PATH.exists():
            try:
                data = json.loads(GPU_STATS_PATH.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except Exception:
                data = {}
        # keep per-module key
        if "embeddings" not in data or not isinstance(data.get("embeddings"), dict):
            data["embeddings"] = {}
        # store history list
        hist = data.get("history", [])
        if not isinstance(hist, list):
            hist = []
        hist.append({"module": "embeddings", **entry})
        # keep last 50
        if len(hist) > 50:
            hist = hist[-50:]
        data["history"] = hist
        data["embeddings"] = entry
        data["last_update"] = entry["timestamp"]
        GPU_STATS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("GPU stats [%s] device=%s allocated=%.1fMB backend=%s", stage, entry["device"], mem.get("allocated_mb", 0), _backend)
        print(f"[embeddings] GPU stats {stage}: device={entry['device']} allocated={mem.get('allocated_mb',0)}MB backend={_backend}")
    except Exception as e:
        logger.debug("write gpu stats fail: %s", e)


def _estimate_tokens(text: str) -> int:
    # ~4 chars per token, at least 1
    est = max(1, int(len(text) / 4))
    # also consider word count
    wc = len(text.split())
    est2 = max(1, int(wc * 1.3))
    return max(est, est2)


def _batch_by_tokens(texts: list[str], max_tokens: int | None = None) -> list[list[str]]:
    if max_tokens is None:
        max_tokens = _MAX_BATCH_TOKENS
        # allow env override dynamic
        try:
            max_tokens = int(os.getenv("JINA_LOCAL_MAX_BATCH_TOKENS", str(max_tokens)))
        except Exception:
            pass
    if max_tokens <= 0:
        return [texts]
    batches: list[list[str]] = []
    cur: list[str] = []
    cur_tokens = 0
    for t in texts:
        tok = _estimate_tokens(t)
        # single text exceeds max -> its own batch
        if tok > max_tokens:
            if cur:
                batches.append(cur)
                cur = []
                cur_tokens = 0
            batches.append([t])
            continue
        if cur_tokens + tok > max_tokens and cur:
            batches.append(cur)
            cur = [t]
            cur_tokens = tok
        else:
            cur.append(t)
            cur_tokens += tok
    if cur:
        batches.append(cur)
    return batches




def _tei_url() -> str:
    return os.getenv("JINA_LOCAL_EMBEDDINGS_URL", "http://127.0.0.1:3001/embed")


def _tei_embed(texts: list[str]) -> list[np.ndarray] | None:
    try:
        import requests
        response = requests.post(_tei_url(), json={"inputs": texts}, timeout=float(os.getenv("JINA_LOCAL_TEI_TIMEOUT", "10")))
        response.raise_for_status()
        payload = response.json()
        vectors = payload if isinstance(payload, list) else payload.get("data", [])
        if vectors and isinstance(vectors[0], dict):
            vectors = [item["embedding"] for item in vectors]
        result = [np.asarray(vector, dtype=np.float32) for vector in vectors]
        if len(result) != len(texts):
            raise ValueError("TEI 返回向量数量不一致")
        return result
    except Exception as exc:
        logger.warning("TEI embeddings unavailable at %s: %s", _tei_url(), exc)
        return None

def _init_backend():
    global _model, _model_name, _DIM, _backend, _device, _model_ref
    if _backend is not None:
        # 懒加载：检查闲置超时，自动释放
        _maybe_release_idle()
        if _backend is not None:
            _touch()
            return _backend
    with _lock:
        if _backend is not None:
            _touch()
            return _backend
        device = _get_device()
        tei_probe = _tei_embed(["__jina_local_healthcheck__"])
        if tei_probe is not None:
            _backend = "tei"
            _DIM = int(tei_probe[0].size)
            _touch()
            _write_gpu_stats("embeddings_tei", {"device": "remote-gpu", "url": _tei_url(), "dim": _DIM})
            return _backend
        # log before
        try:
            mem_before = _gpu_memory_mb()
            logger.info("Embeddings init start device=%s mem_before=%.1fMB", device, mem_before.get("allocated_mb", 0))
            print(f"[embeddings] init start device={device} mem_before={mem_before.get('allocated_mb',0)}MB")
        except Exception:
            pass
        # try sentence-transformers
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            for mid in _CANDIDATE_MODELS:
                try:
                    kwargs = dict(device=device, local_files_only=True, trust_remote_code=True)
                    # try float16 for bge-m3 on cuda
                    is_bge = "bge-m3" in mid.lower()
                    use_fp16 = device.startswith("cuda") and is_bge
                    if use_fp16:
                        # try torch_dtype then half fallback
                        try:
                            import torch  # type: ignore

                            # attempt with model_kwargs
                            kwargs["model_kwargs"] = {"torch_dtype": torch.float16}  # type: ignore
                        except Exception:
                            pass
                    m = SentenceTransformer(mid, **kwargs)  # type: ignore
                    # if fp16 requested and model not yet half, try half()
                    if use_fp16:
                        try:
                            m.half()  # type: ignore
                            logger.info("Embeddings model half() applied for %s on %s", mid, device)
                        except Exception as e:
                            logger.debug("half() fail %s: %s", mid, e)
                    _model = m
                    _model_name = mid
                    try:
                        _DIM = int(m.get_sentence_embedding_dimension())  # type: ignore
                    except Exception:
                        _DIM = 384
                    _backend = "hf"
                    _touch()
                    try:
                        _model_ref = weakref.ref(m)
                    except Exception:
                        _model_ref = None
                    logger.info("Embeddings backend: HF model %s dim=%s device=%s dtype=%s", mid, _DIM, device, "float16" if use_fp16 else "float32")
                    _write_gpu_stats("embeddings_loaded", {"model": mid, "device": device, "dim": _DIM})
                    try:
                        mem_after = _gpu_memory_mb()
                        logger.info("Embeddings mem after load allocated=%.1fMB", mem_after.get("allocated_mb", 0))
                        print(f"[embeddings] loaded {mid} device={device} dim={_DIM} mem_after={mem_after.get('allocated_mb',0)}MB")
                    except Exception:
                        pass
                    return _backend
                except Exception as e:
                    logger.debug("HF local load fail %s on %s: %s", mid, device, e)
                    continue
            # allow download if enabled
            try:
                if os.getenv("JINA_LOCAL_ALLOW_DOWNLOAD", "0") == "1":
                    mid = "sentence-transformers/all-MiniLM-L6-v2"
                    m = SentenceTransformer(mid, device=device, trust_remote_code=True)  # type: ignore
                    if device.startswith("cuda"):
                        try:
                            m.half()  # type: ignore
                        except Exception:
                            pass
                    _model = m
                    _model_name = mid
                    _DIM = int(m.get_sentence_embedding_dimension())  # type: ignore
                    _backend = "hf"
                    _touch()
                    try:
                        _model_ref = weakref.ref(m)
                    except Exception:
                        _model_ref = None
                    logger.info("Embeddings backend: HF downloaded %s dim=%s device=%s", mid, _DIM, device)
                    _write_gpu_stats("embeddings_downloaded", {"model": mid, "device": device, "dim": _DIM})
                    return _backend
            except Exception as e:
                logger.debug("HF download fail: %s", e)
        except ImportError as e:
            logger.debug("sentence-transformers not installed: %s", e)
        except Exception as e:
            logger.debug("embeddings backend init error: %s", e)

        _backend = "hash"
        _DIM = 384
        _touch()
        logger.info("Embeddings backend: hash fallback dim=%s device=%s", _DIM, device)
        _write_gpu_stats("embeddings_hash_fallback", {"dim": _DIM, "device": device})
        return _backend


def _get_dim() -> int:
    _init_backend()
    return _DIM


def _cache_path(text: str) -> pathlib.Path:
    raw = f"{_backend or 'unknown'}|||{_model_name or 'tei'}|||{text}"
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"embed-{h}.npy"


def _validate_texts(texts) -> list[str]:
    if texts is None:
        raise TypeError("texts 必须为 list[str]，不能为 None")
    if not isinstance(texts, list):
        raise TypeError("texts 必须为 list[str]")
    if len(texts) == 0:
        raise ValueError("texts 不能为空列表")
    for t in texts:
        if not isinstance(t, str):
            raise TypeError("texts 元素必须为 str")
        if not t.strip():
            raise ValueError("texts 元素不能为空字符串")
    return texts


def _validate_one(text) -> str:
    if text is None:
        raise TypeError("text 必须为非空字符串，不能为 None")
    if not isinstance(text, str):
        raise TypeError("text 必须为 str")
    if not text.strip():
        raise ValueError("text 不能为空字符串")
    return text


def _hash_embed_one(text: str, dim: int) -> np.ndarray:
    vec = np.zeros(dim, dtype=np.float32)
    tokens = re.findall(r"[A-Za-z0-9]+", text.lower())
    if not tokens:
        tokens = [text.lower().strip()]
    for tok in tokens:
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16) % dim
        vec[h] += 1.0
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.astype(np.float32)


def _hf_embed_batch(texts: list[str]) -> list[np.ndarray]:
    _init_backend()
    assert _model is not None
    # handle batch slicing externally, but also ensure single batch call works
    try:
        vecs = _model.encode(texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)  # type: ignore
        if isinstance(vecs, np.ndarray) and vecs.ndim == 2:
            return [vecs[i].astype(np.float32) for i in range(vecs.shape[0])]
        return [np.array(v, dtype=np.float32) for v in vecs]
    except TypeError:
        vecs = _model.encode(texts, convert_to_numpy=True, show_progress_bar=False)  # type: ignore
        out = []
        for v in vecs:
            arr = np.array(v, dtype=np.float32)
            n = np.linalg.norm(arr)
            if n > 0:
                arr = arr / n
            out.append(arr)
        return out


def _encode_single(text: str) -> np.ndarray:
    _init_backend()
    if _backend == "hf" and _model is not None:
        vecs = _hf_embed_batch([text])
        return vecs[0]
    else:
        dim = _get_dim()
        return _hash_embed_one(text, dim)


def embed(texts: list[str]) -> list[list[float]]:
    """批量嵌入，L2 归一化，带文件缓存，支持 max_batch_tokens 分片"""
    _validate_texts(texts)
    _init_backend()
    dim = _get_dim()
    cached: dict[int, np.ndarray] = {}
    to_compute_idx: list[int] = []
    to_compute_texts: list[str] = []
    for i, t in enumerate(texts):
        p = _cache_path(t)
        if p.exists():
            try:
                arr = np.load(p)
                if isinstance(arr, np.ndarray) and arr.size == dim:
                    n = np.linalg.norm(arr)
                    if n > 0 and abs(n - 1.0) > 1e-4:
                        arr = arr / n
                    cached[i] = arr.astype(np.float32)
                    continue
            except Exception as e:
                logger.debug("cache load fail %s: %s", p, e)
        to_compute_idx.append(i)
        to_compute_texts.append(t)

    computed: dict[int, np.ndarray] = {}
    if to_compute_texts:
        if _backend == "tei":
            vectors = _tei_embed(to_compute_texts)
            if vectors is None:
                raise RuntimeError("TEI 后端在初始化后不可用")
            for idx, vec in zip(to_compute_idx, vectors):
                computed[idx] = vec
        elif _backend == "hf" and _model is not None:
            # batch slicing by max_batch_tokens
            batches = _batch_by_tokens(to_compute_texts)
            # need to map global idx -> vec
            # flatten batches but keep order
            vecs_all: list[np.ndarray] = []
            for batch in batches:
                vecs = _hf_embed_batch(batch)
                vecs_all.extend(vecs)
            # vecs_all order matches to_compute_texts order
            for idx, vec in zip(to_compute_idx, vecs_all):
                computed[idx] = vec
        else:
            for idx, txt in zip(to_compute_idx, to_compute_texts):
                computed[idx] = _hash_embed_one(txt, dim)
        for idx, txt in zip(to_compute_idx, to_compute_texts):
            vec = computed[idx]
            try:
                np.save(_cache_path(txt), vec)
            except Exception as e:
                logger.debug("cache save fail %s: %s", txt[:30], e)

    all_vecs: dict[int, np.ndarray] = {**cached, **computed}
    out: list[list[float]] = []
    for i in range(len(texts)):
        arr = all_vecs.get(i)
        if arr is None:
            arr = _hash_embed_one(texts[i], dim)
        n = np.linalg.norm(arr)
        if n > 0 and abs(n - 1.0) > 1e-4:
            arr = arr / n
        out.append(arr.astype(np.float32).tolist())
    return out


def embed_one(text: str) -> list[float]:
    _validate_one(text)
    p = _cache_path(text)
    if p.exists():
        try:
            arr = np.load(p)
            if isinstance(arr, np.ndarray) and arr.size == _get_dim():
                n = np.linalg.norm(arr)
                if n > 0 and abs(n - 1.0) > 1e-4:
                    arr = arr / n
                return arr.astype(np.float32).tolist()
        except Exception:
            pass
    vec = _encode_single(text)
    try:
        np.save(p, vec)
    except Exception:
        pass
    n = np.linalg.norm(vec)
    if n > 0 and abs(n - 1.0) > 1e-4:
        vec = vec / n
    return vec.astype(np.float32).tolist()


embeddings = embed
encode = embed
encode_one = embed_one

def get_dimension() -> int:
    return _get_dim()

def get_backend() -> str:
    _init_backend()
    return _backend or "hash"

def get_device() -> str:
    return _get_device()

def get_gpu_stats() -> dict:
    try:
        if GPU_STATS_PATH.exists():
            return json.loads(GPU_STATS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"memory": _gpu_memory_mb(), "device": _get_device(), "backend": _backend}

def release_model():
    """手动释放模型（闲置超时自动亦会释放），weakref 保留可探测"""
    _release_backend()
    return {"released": True, "backend": _backend, "lazy": _JINA_LAZY, "idle_timeout": _IDLE_TIMEOUT}

# eager 模式：启动即加载（默认懒加载，不执行）
if not _JINA_LAZY:
    try:
        _init_backend()
    except Exception as e:
        logger.debug("eager init fail: %s", e)
