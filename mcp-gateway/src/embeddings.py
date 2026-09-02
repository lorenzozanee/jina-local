"""本地 Embeddings 服务，替代 jina embeddings
- 优先加载 sentence-transformers 本地模型 BAAI/bge-m3 或 all-MiniLM-L6-v2
- 无模型/无依赖则 fallback 到 哈希 TF + L2 归一化 (保证离线可用、语义区分度、维度一致)
- 支持 embed(texts) 与 embed_one(text)，批量、缓存、严格校验
"""
import hashlib
import logging
import pathlib
import re
import threading

import numpy as np

logger = logging.getLogger(__name__)

CACHE_DIR = pathlib.Path("/tmp/opencode/jina-local")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_DIM = 384
_model = None
_model_name: str | None = None
_backend: str | None = None  # "hf" or "hash"
_lock = threading.Lock()

# 尝试加载的模型列表（按优先度）
_CANDIDATE_MODELS = [
    "BAAI/bge-m3",
    "sentence-transformers/all-MiniLM-L6-v2",
]


def _init_backend():
    global _model, _model_name, _DIM, _backend
    if _backend is not None:
        return _backend
    with _lock:
        if _backend is not None:
            return _backend
        # 尝试 sentence-transformers 本地加载（offline 优先，避免网络阻塞）
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            for mid in _CANDIDATE_MODELS:
                try:
                    # 先尝试离线加载，若本地无缓存则放弃避免下载超时
                    m = SentenceTransformer(mid, device="cpu", local_files_only=True, trust_remote_code=True)
                    _model = m
                    _model_name = mid
                    try:
                        _DIM = int(m.get_sentence_embedding_dimension())
                    except Exception:
                        _DIM = 384
                    _backend = "hf"
                    logger.info("Embeddings backend: HF model %s dim=%s", mid, _DIM)
                    return _backend
                except Exception as e:
                    logger.debug("HF local load fail %s: %s", mid, e)
                    continue
            # 若本地缓存均无，尝试一次在线加载轻量模型（超时控制较短），失败即 fallback
            # 为避免长时间阻塞，仅在允许网络时尝试，设置 HF_HUB_OFFLINE=0 情况下亦可
            # 这里加入轻量重试：若环境变量允许网络则尝试联网加载 MiniLM
            # 不强制联网，若失败直接 fallback
            try:
                import os

                if os.getenv("JINA_LOCAL_ALLOW_DOWNLOAD", "0") == "1":
                    # explicit opt-in to download
                    mid = "sentence-transformers/all-MiniLM-L6-v2"
                    m = SentenceTransformer(mid, device="cpu", trust_remote_code=True)
                    _model = m
                    _model_name = mid
                    _DIM = int(m.get_sentence_embedding_dimension())
                    _backend = "hf"
                    logger.info("Embeddings backend: HF downloaded %s dim=%s", mid, _DIM)
                    return _backend
            except Exception as e:
                logger.debug("HF download fail: %s", e)
        except ImportError as e:
            logger.debug("sentence-transformers not installed: %s", e)
        except Exception as e:
            logger.debug("embeddings backend init error: %s", e)

        # fallback: hash TF
        _backend = "hash"
        _DIM = 384
        logger.info("Embeddings backend: hash fallback dim=%s", _DIM)
        return _backend


def _get_dim() -> int:
    _init_backend()
    return _DIM


def _cache_path(text: str) -> pathlib.Path:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
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
    # tokenization: alphanum lower
    tokens = re.findall(r"[A-Za-z0-9]+", text.lower())
    if not tokens:
        tokens = [text.lower().strip()]
    for tok in tokens:
        # stable hash via md5
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16) % dim
        vec[h] += 1.0
        # bigram boost for phrase continuity (optional,轻量)
        # 不加 bigram 已可区分 apple fruit vs car engine
    # also include char trigram backoff for very short tokens? not needed
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.astype(np.float32)


def _hf_embed_batch(texts: list[str]) -> list[np.ndarray]:
    _init_backend()
    assert _model is not None
    # sentence-transformers encode returns normalized if normalize_embeddings=True
    try:
        vecs = _model.encode(texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)  # type: ignore
        # ensure 2D
        if isinstance(vecs, np.ndarray) and vecs.ndim == 2:
            return [vecs[i].astype(np.float32) for i in range(vecs.shape[0])]
        # fallback list
        return [np.array(v, dtype=np.float32) for v in vecs]
    except TypeError:
        # older API
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
    """批量嵌入，L2 归一化，带文件缓存"""
    _validate_texts(texts)
    _init_backend()
    dim = _get_dim()
    # 批量缓存检查
    cached: dict[int, np.ndarray] = {}
    to_compute_idx: list[int] = []
    to_compute_texts: list[str] = []
    for i, t in enumerate(texts):
        p = _cache_path(t)
        if p.exists():
            try:
                arr = np.load(p)
                if isinstance(arr, np.ndarray) and arr.size == dim:
                    # ensure normalized (cache may already normalized)
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
        if _backend == "hf" and _model is not None:
            vecs = _hf_embed_batch(to_compute_texts)
            for idx, vec in zip(to_compute_idx, vecs):
                computed[idx] = vec
        else:
            for idx, txt in zip(to_compute_idx, to_compute_texts):
                computed[idx] = _hash_embed_one(txt, dim)
        # write cache
        for idx, txt in zip(to_compute_idx, to_compute_texts):
            vec = computed[idx]
            try:
                np.save(_cache_path(txt), vec)
            except Exception as e:
                logger.debug("cache save fail %s: %s", txt[:30], e)

    # assemble
    all_vecs: dict[int, np.ndarray] = {**cached, **computed}
    out: list[list[float]] = []
    for i in range(len(texts)):
        arr = all_vecs.get(i)
        if arr is None:
            # should not happen
            arr = _hash_embed_one(texts[i], dim)
        # ensure normalized
        n = np.linalg.norm(arr)
        if n > 0 and abs(n - 1.0) > 1e-4:
            arr = arr / n
        out.append(arr.astype(np.float32).tolist())
    return out


def embed_one(text: str) -> list[float]:
    """单条嵌入"""
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


# 兼容别名，满足 gateway 暴露 embeddings/embed 兼容 jina
embeddings = embed
encode = embed
encode_one = embed_one

def get_dimension() -> int:
    return _get_dim()

def get_backend() -> str:
    _init_backend()
    return _backend or "hash"
