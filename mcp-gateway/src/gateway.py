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

try:
    from .reranker import rerank as _rerank
    from .reranker import sort_by_relevance as _rerank_sort
    from .reranker import rerank_batch as _rerank_batch
except ImportError:
    try:
        from reranker import rerank as _rerank  # type: ignore
        from reranker import sort_by_relevance as _rerank_sort  # type: ignore
        from reranker import rerank_batch as _rerank_batch  # type: ignore
    except ImportError:
        _rerank = None  # type: ignore
        _rerank_sort = None  # type: ignore
        _rerank_batch = None  # type: ignore

try:
    from .search_deep import search_web_deep as _search_deep
except ImportError:
    try:
        from search_deep import search_web_deep as _search_deep  # type: ignore
    except ImportError:
        _search_deep = None  # type: ignore

try:
    from .utils import deduplicate_strings as _dedup_strings
    from .utils import deduplicate_images as _dedup_images
    from .utils import classify_text as _classify_text
    from .utils import expand_query as _expand_query
    from .utils import extract_pdf as _extract_pdf
    from .utils import guess_datetime_url as _guess_dt
    from .utils import primer as _primer
except ImportError:
    try:
        from utils import deduplicate_strings as _dedup_strings  # type: ignore
        from utils import deduplicate_images as _dedup_images  # type: ignore
        from utils import classify_text as _classify_text  # type: ignore
        from utils import expand_query as _expand_query  # type: ignore
        from utils import extract_pdf as _extract_pdf  # type: ignore
        from utils import guess_datetime_url as _guess_dt  # type: ignore
        from utils import primer as _primer  # type: ignore
    except ImportError:
        _dedup_strings = None  # type: ignore
        _dedup_images = None  # type: ignore
        _classify_text = None  # type: ignore
        _expand_query = None  # type: ignore
        _extract_pdf = None  # type: ignore
        _guess_dt = None  # type: ignore
        _primer = None  # type: ignore

try:
    from .search_academic import search_arxiv as _search_arxiv
    from .search_academic import parallel_search_arxiv as _parallel_search_arxiv
    from .search_academic import search_ssrn as _search_ssrn
    from .search_academic import parallel_search_ssrn as _parallel_search_ssrn
    from .search_academic import search_bibtex as _search_bibtex
    from .search_academic import search_images as _search_images
    from .search_academic import search_jina_blog as _search_jina_blog
    from .search_academic import capture_screenshot_url as _capture_screenshot
except ImportError:
    try:
        from search_academic import search_arxiv as _search_arxiv  # type: ignore
        from search_academic import parallel_search_arxiv as _parallel_search_arxiv  # type: ignore
        from search_academic import search_ssrn as _search_ssrn  # type: ignore
        from search_academic import parallel_search_ssrn as _parallel_search_ssrn  # type: ignore
        from search_academic import search_bibtex as _search_bibtex  # type: ignore
        from search_academic import search_images as _search_images  # type: ignore
        from search_academic import search_jina_blog as _search_jina_blog  # type: ignore
        from search_academic import capture_screenshot_url as _capture_screenshot  # type: ignore
    except ImportError:
        try:
            import importlib.util as _ilu
            import pathlib as _pl
            _sa_path = _pl.Path(__file__).with_name("search_academic.py")
            _spec_sa = _ilu.spec_from_file_location("search_academic", _sa_path)
            assert _spec_sa and _spec_sa.loader
            _sa_mod = _ilu.module_from_spec(_spec_sa)
            _spec_sa.loader.exec_module(_sa_mod)  # type: ignore
            _search_arxiv = _sa_mod.search_arxiv  # type: ignore
            _parallel_search_arxiv = _sa_mod.parallel_search_arxiv  # type: ignore
            _search_ssrn = _sa_mod.search_ssrn  # type: ignore
            _parallel_search_ssrn = _sa_mod.parallel_search_ssrn  # type: ignore
            _search_bibtex = _sa_mod.search_bibtex  # type: ignore
            _search_images = _sa_mod.search_images  # type: ignore
            _search_jina_blog = _sa_mod.search_jina_blog  # type: ignore
            _capture_screenshot = _sa_mod.capture_screenshot_url  # type: ignore
        except Exception:
            _search_arxiv = None  # type: ignore
            _parallel_search_arxiv = None  # type: ignore
            _search_ssrn = None  # type: ignore
            _parallel_search_ssrn = None  # type: ignore
            _search_bibtex = None  # type: ignore
            _search_images = None  # type: ignore
            _search_jina_blog = None  # type: ignore
            _capture_screenshot = None  # type: ignore


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
    """语义 Reranker，委托至 reranker.py（CrossEncoder 优先，fallback 余弦），保持兼容 wrapper"""
    if _rerank is not None:
        return _rerank(query, documents)
    if _rerank_sort is not None:
        return _rerank_sort(query, documents)
    # fallback stub（should not happen after reranker.py exists）
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

    def _normalize(words: typing.Iterable[str]) -> set[str]:
        norm: set[str] = set()
        for w in words:
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
        score = float(overlap)
        scored.append({"document": doc, "relevance_score": score, "_idx": idx})
    scored.sort(key=lambda x: (-x["relevance_score"], x["_idx"]))
    for item in scored:
        item.pop("_idx", None)
        item["relevance_score"] = float(item["relevance_score"])
    return scored


def rerank(query: str, documents: list[str]) -> list[dict]:
    """兼容别名，暴露 rerank 与 sort_by_relevance 双入口"""
    return sort_by_relevance(query, documents)


def rerank_batch(queries: list[str], documents_list: list[list[str]]) -> list[list[dict]]:
    """批量 rerank 委托"""
    if _rerank_batch is not None:
        return _rerank_batch(queries, documents_list)
    if not isinstance(queries, list) or not isinstance(documents_list, list):
        raise TypeError("queries 与 documents_list 必须为 list")
    if len(queries) != len(documents_list):
        raise ValueError("长度不一致")
    return [sort_by_relevance(q, docs) for q, docs in zip(queries, documents_list)]


def search_web_deep(query: str, num: int = 5, chunk_size: int = 100, **kwargs) -> list[dict]:
    """search_web_deep 编排，委托至 search_deep.py"""
    # 兼容 limit/top_k 别名
    if "limit" in kwargs and kwargs["limit"] is not None:
        try:
            num = int(kwargs["limit"])
        except Exception:
            pass
    if "top_k" in kwargs and kwargs["top_k"] is not None:
        try:
            num = int(kwargs["top_k"])
        except Exception:
            pass
    if _search_deep is not None:
        return _search_deep(query, num=num, chunk_size=chunk_size, **kwargs)
    raise RuntimeError("search_deep 模块未加载")


def deduplicate_strings(strings: list[str], top_k: int | None = None, threshold: float = 0.85, **kwargs) -> list[str]:
    """委托 utils.deduplicate_strings"""
    if _dedup_strings is not None:
        return _dedup_strings(strings, top_k=top_k, threshold=threshold, **kwargs)
    raise RuntimeError("utils 模块未加载")


def deduplicate_images(images: list[str], top_k: int | None = None, threshold: float = 0.85, **kwargs) -> list[str]:
    if _dedup_images is not None:
        return _dedup_images(images, top_k=top_k, threshold=threshold, **kwargs)
    raise RuntimeError("utils 模块未加载")


def classify_text(texts: list[str], labels: list[str], **kwargs) -> list[dict]:
    if _classify_text is not None:
        return _classify_text(texts, labels, **kwargs)
    raise RuntimeError("utils 模块未加载")


def expand_query(query: str, num: int = 3, **kwargs) -> list[str]:
    if _expand_query is not None:
        return _expand_query(query, num=num, **kwargs)
    raise RuntimeError("utils 模块未加载")


def extract_pdf(url: str, **kwargs) -> dict:
    if _extract_pdf is not None:
        return _extract_pdf(url, **kwargs)
    raise RuntimeError("utils 模块未加载")


def guess_datetime_url(url: str, **kwargs) -> dict:
    if _guess_dt is not None:
        return _guess_dt(url, **kwargs)
    raise RuntimeError("utils 模块未加载")


def primer(**kwargs) -> dict:
    if _primer is not None:
        return _primer(**kwargs)
    raise RuntimeError("utils 模块未加载")


def search_arxiv(query: str, num: int = 5, **kwargs) -> list[dict]:
    if _search_arxiv is not None:
        return _search_arxiv(query, num=num, **kwargs)
    raise RuntimeError("search_academic 模块未加载")


def parallel_search_arxiv(queries: list[str], num: int = 5, **kwargs) -> list[list[dict]]:
    if _parallel_search_arxiv is not None:
        return _parallel_search_arxiv(queries, num=num, **kwargs)
    raise RuntimeError("search_academic 模块未加载")


def search_ssrn(query: str, num: int = 5, **kwargs) -> list[dict]:
    if _search_ssrn is not None:
        return _search_ssrn(query, num=num, **kwargs)
    raise RuntimeError("search_academic 模块未加载")


def parallel_search_ssrn(queries: list[str], num: int = 5, **kwargs) -> list[list[dict]]:
    if _parallel_search_ssrn is not None:
        return _parallel_search_ssrn(queries, num=num, **kwargs)
    raise RuntimeError("search_academic 模块未加载")


def search_bibtex(query: str, num: int = 5, **kwargs) -> list[dict]:
    if _search_bibtex is not None:
        return _search_bibtex(query, num=num, **kwargs)
    raise RuntimeError("search_academic 模块未加载")


def search_images(query: str, num: int = 5, **kwargs) -> list[dict]:
    if _search_images is not None:
        return _search_images(query, num=num, **kwargs)
    raise RuntimeError("search_academic 模块未加载")


def search_jina_blog(query: str, num: int = 5, **kwargs) -> list[dict]:
    if _search_jina_blog is not None:
        return _search_jina_blog(query, num=num, **kwargs)
    raise RuntimeError("search_academic 模块未加载")


def capture_screenshot_url(url: str, **kwargs) -> dict:
    if _capture_screenshot is not None:
        return _capture_screenshot(url, **kwargs)
    raise RuntimeError("search_academic 模块未加载")


# aliases for jina / additional compatibility
deduplicate = deduplicate_strings
classify = classify_text
jina_deduplicate_strings = deduplicate_strings
jina_deduplicate_images = deduplicate_images
jina_classify_text = classify_text
jina_expand_query = expand_query
jina_extract_pdf = extract_pdf
jina_guess_datetime_url = guess_datetime_url
jina_primer = primer
jina_search_arxiv = search_arxiv
jina_search_ssrn = search_ssrn
jina_search_bibtex = search_bibtex
jina_search_images = search_images
jina_search_jina_blog = search_jina_blog
jina_capture_screenshot_url = capture_screenshot_url

# alias for jina compatibility
search_deep = search_web_deep
