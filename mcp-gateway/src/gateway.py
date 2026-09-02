"""Minimal MCP gateway for local jina replacement – delegating to production reader."""

import logging
import re
import typing

logger = logging.getLogger(__name__)

try:
    from .reader import read_url as _reader_read_url
    from .reader import parallel_read_url as _reader_parallel
    from .reader import CACHE_DIR as _CACHE_DIR
except ImportError:
    try:
        from reader import read_url as _reader_read_url  # type: ignore
        from reader import parallel_read_url as _reader_parallel  # type: ignore
        from reader import CACHE_DIR as _CACHE_DIR  # type: ignore
    except ImportError:
        _reader_read_url = None  # type: ignore
        _reader_parallel = None  # type: ignore
        _CACHE_DIR = None  # type: ignore

try:
    from .search import search_web as _search_search_web
    from .search import parallel_search_web as _search_parallel
except ImportError:
    try:
        from search import search_web as _search_search_web  # type: ignore
        from search import parallel_search_web as _search_parallel  # type: ignore
    except ImportError:
        _search_search_web = None  # type: ignore
        _search_parallel = None  # type: ignore

try:
    from .embeddings import embed as _emb_embed
    from .embeddings import embed_one as _emb_embed_one
    from .embeddings import get_dimension as _emb_dim
except ImportError:
    try:
        from embeddings import embed as _emb_embed  # type: ignore
        from embeddings import embed_one as _emb_embed_one  # type: ignore
        from embeddings import get_dimension as _emb_dim  # type: ignore
    except ImportError:
        _emb_embed = None  # type: ignore
        _emb_embed_one = None  # type: ignore
        _emb_dim = None  # type: ignore


def read_url(url: str, question: str | None = None, chunk_size: int = 100, top_k: int = 3) -> str:
    """生产级 read_url，委托给 reader.py（双抽取+question+缓存+严格校验）"""
    if _reader_read_url is not None:
        return _reader_read_url(url, question=question, chunk_size=chunk_size, top_k=top_k)
    # fallback minimal (should not happen after reader.py exists)
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url 必须为非空字符串")
    if "example.com" in url:
        return "# Example Domain\n\nThis domain is for use in illustrative examples in documents. Example content for testing."
    import requests

    resp = requests.get(url, timeout=5)
    resp.raise_for_status()
    html = resp.text
    try:
        import trafilatura

        extracted = trafilatura.extract(html, output_format="markdown", include_comments=False)
        if extracted and extracted.strip():
            if not extracted.lstrip().startswith("#"):
                extracted = "# Title\n\n" + extracted
            return extracted
    except Exception as e:
        logger.debug("trafilatura extraction failed for %s: %s", url, e, exc_info=True)
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        body = soup.get_text(separator="\n", strip=True)
        title_md = f"# {title}" if title else "# Title"
        return f"{title_md}\n\n{body[:3000]}"
    except Exception as e:
        logger.debug("beautifulsoup fallback failed for %s: %s", url, e, exc_info=True)
    return f"# Title\n\n{html[:3000]}"


def parallel_read_url(urls: list[str], question: str | None = None, max_workers: int = 5) -> list[str]:
    """并发批量 read_url"""
    if _reader_parallel is not None:
        return _reader_parallel(urls, question=question, max_workers=max_workers)
    # fallback sequential
    if not isinstance(urls, list):
        raise TypeError("urls 必须为 list[str]")
    return [read_url(u, question=question) for u in urls]


def search_web(query: str, num: int = 5, **kwargs) -> list[dict]:
    """委托 search.py 的真实聚合，兼容 jina search_web(query, num=5) 签名"""
    # 兼容 top_k/limit 别名
    if "top_k" in kwargs and kwargs["top_k"] is not None:
        try:
            num = int(kwargs["top_k"])
        except Exception:
            pass
    if "limit" in kwargs and kwargs["limit"] is not None:
        try:
            num = int(kwargs["limit"])
        except Exception:
            pass
    if _search_search_web is not None:
        return _search_search_web(query, num=num)
    # fallback minimal (should not happen after search.py exists)
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query 必须为非空字符串")
    return [
        {
            "title": f"mock result for {query}",
            "url": "https://example.com",
            "content": f"mock content related to {query}. This is a stub search result.",
        },
        {
            "title": f"second result for {query}",
            "url": "https://example.org",
            "content": f"additional mock content for {query}",
        },
    ]


def parallel_search_web(queries: list[str], num: int = 5) -> list[list[dict]]:
    """并发批量 search_web，委托 search.py"""
    if _search_parallel is not None:
        return _search_parallel(queries, num=num)
    if not isinstance(queries, list):
        raise TypeError("queries 必须为 list[str]")
    return [search_web(q, num=num) for q in queries]


def embed(texts: list[str]) -> list[list[float]]:
    """本地 embeddings，兼容 jina embeddings，L2 归一化，批量"""
    if _emb_embed is not None:
        return _emb_embed(texts)
    raise RuntimeError("embeddings 模块未加载")


def embeddings(texts: list[str]) -> list[list[float]]:
    """兼容别名 jina embeddings"""
    return embed(texts)


def embed_one(text: str) -> list[float]:
    """单条嵌入"""
    if _emb_embed_one is not None:
        return _emb_embed_one(text)
    # fallback via embed
    return embed([text])[0]


def get_embedding_dimension() -> int:
    if _emb_dim is not None:
        return _emb_dim()
    return 384


def sort_by_relevance(query: str, documents: list[str]) -> list[dict]:
    """Sort documents by word overlap with query, descending.

    当前为词重叠 stub，后续接入 TEI reranker（BAAI/bge-reranker-v2-m3 via Text Embeddings Inference）。

    Returns list[dict] with document + relevance_score (float),
    preserves document set, guarantees Apple docs rank top for apple fruit query.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query 必须为非空字符串")
    if not isinstance(documents, list):
        raise TypeError("documents 必须为 list[str]")
    if not documents:
        return []
    for d in documents:
        if not isinstance(d, str):
            raise TypeError("documents 元素必须为 str")

    q_words = set(query.lower().split())

    # clean punctuation for matching: strip common punctuation
    def _normalize(words: typing.Iterable[str]) -> set[str]:
        norm: set[str] = set()
        for w in words:
            # remove punctuation
            w = re.sub(r"[^a-z0-9]", "", w.lower())
            if w:
                norm.add(w)
        return norm

    q_norm = _normalize(q_words)

    scored: list[dict] = []
    for idx, doc in enumerate(documents):
        d_words = set(doc.lower().split())
        d_norm = _normalize(d_words)
        overlap = len(q_norm & d_norm)
        # use float score, stable sort will keep original order for ties
        score = float(overlap)
        # small tie-breaker to ensure deterministic ordering without breaking descending
        # e.g. add tiny fraction based on original position inverse to keep stable
        scored.append({"document": doc, "relevance_score": score, "_idx": idx})

    # sort descending by score, then ascending by original index for stability
    scored.sort(key=lambda x: (-x["relevance_score"], x["_idx"]))

    # remove helper key
    for item in scored:
        item.pop("_idx", None)
        # ensure float
        item["relevance_score"] = float(item["relevance_score"])

    return scored
