"""本地 Search 聚合：仅返回可追溯的检索结果。"""
import hashlib
import json
import logging
import os
import pathlib
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

import requests
from bs4 import BeautifulSoup

try:
    from .search_lifecycle import SearchLifecycleError, get_search_lifecycle
except ImportError:
    from search_lifecycle import SearchLifecycleError, get_search_lifecycle

logger = logging.getLogger(__name__)

CACHE_DIR = pathlib.Path("/tmp/opencode/jina-local")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://127.0.0.1:8081")
SEARCH_FETCHER_URL = os.getenv("JINA_LOCAL_SEARCH_FETCHER_URL", "http://127.0.0.1:8082")
SEARCH_CORE_URL = os.getenv("JINA_LOCAL_SEARCH_CORE_URL", "http://127.0.0.1:8083")
SEARXNG_TIMEOUT = 5
DEFAULT_NUM = 5
SEARCH_TIMEOUT = 5
SEARCH_CACHE_TTL_SECONDS = float(os.getenv("JINA_LOCAL_SEARCH_CACHE_TTL_SECONDS", "300"))
CACHE_SCHEMA_VERSION = 2
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Real-IP": "127.0.0.1",
    "X-Forwarded-For": "127.0.0.1",
}


class SearchUnavailableError(RuntimeError):
    """Raised when every configured search backend is unavailable or empty."""

    code = "NO_RETRIEVAL_BACKEND"

    def __init__(self, message: str = code):
        super().__init__(message)


def _validate_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query 必须为非空字符串")
    return query.strip()


def _cache_path(query: str) -> pathlib.Path:
    key = hashlib.sha256(query.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"search-{key}.json"


def _is_provenanced_result(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    return all(isinstance(item.get(field), str) and item[field].strip() for field in (
        "title", "url", "content", "source", "retrieved_at"
    ))


def _discard_cache(path: pathlib.Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("cache discard failed %s: %s", path, exc)


def _read_cache(query: str) -> list[dict] | None:
    p = _cache_path(query)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                _discard_cache(p)
                return None
            if data.get("schema_version") != CACHE_SCHEMA_VERSION or data.get("query") != query:
                _discard_cache(p)
                return None
            expires_at = data.get("expires_at")
            results = data.get("results")
            if not isinstance(expires_at, (int, float)) or expires_at <= time.time():
                _discard_cache(p)
                return None
            if isinstance(results, list) and results and all(_is_provenanced_result(item) for item in results):
                return results
            _discard_cache(p)
        except Exception as e:
            logger.debug("cache read fail %s: %s", query, e)
            _discard_cache(p)
    return None


def _write_cache(query: str, results: list[dict]) -> None:
    if not results or not all(_is_provenanced_result(item) for item in results):
        return
    p = _cache_path(query)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        payload = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "query": query,
            "created_at": now,
            "expires_at": now + SEARCH_CACHE_TTL_SECONDS,
            "results": results,
        }
        temporary = p.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(p)
    except Exception as e:
        logger.debug("cache write fail %s: %s", query, e)


def _retrieved_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _with_provenance(title: str, url: str, content: str, source: str) -> dict:
    return {
        "title": title,
        "url": url,
        "content": content,
        "source": source,
        "retrieved_at": _retrieved_at(),
    }


def _normalize_url(url: str) -> str:
    """归一化 url 用于去重：小写 host、去 fragment、去 trailing slash、去 utm 参数、解码"""
    try:
        u = url.strip()
        parsed = urllib.parse.urlparse(u)
        scheme = (parsed.scheme or "https").lower()
        netloc = parsed.netloc.lower()
        # 去掉默认端口
        if netloc.endswith(":80") and scheme == "http":
            netloc = netloc[:-3]
        if netloc.endswith(":443") and scheme == "https":
            netloc = netloc[:-4]
        # path: 去 trailing slash (保留根 /)
        path = urllib.parse.unquote(parsed.path or "/")
        # normalize double slashes
        path = re.sub(r"/{2,}", "/", path)
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")
        # query: 去掉 utm_* 参数，排序
        qs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        filtered = [(k, v) for k, v in qs if not k.lower().startswith("utm_")]
        filtered.sort()
        query = urllib.parse.urlencode(filtered)
        # 重组 (去掉 fragment、params)
        normalized = urllib.parse.urlunparse((scheme, netloc, path, "", query, ""))
        return normalized
    except Exception:
        return url.strip().rstrip("/").lower()


def _dedup_results(results: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for r in results:
        url = r.get("url", "")
        if not isinstance(url, str) or not url.strip():
            continue
        key = _normalize_url(url)
        if key not in seen:
            seen[key] = r
    return list(seen.values())


# 别名兼容测试
_dedup = _dedup_results


def _rank_results(results: list[dict], query: str, title_weight: float = 2.0) -> list[dict]:
    """按 query 词重叠加标题权重排序"""
    if not query or not results:
        return results

    def _norm_words(s: str) -> set[str]:
        return set(re.sub(r"[^a-z0-9]", " ", s.lower()).split()) - {""}

    q_words = _norm_words(query)
    if not q_words:
        return results

    scored = []
    for idx, r in enumerate(results):
        title = r.get("title", "") or ""
        content = r.get("content", "") or ""
        t_words = _norm_words(title)
        c_words = _norm_words(content)
        t_overlap = len(q_words & t_words)
        c_overlap = len(q_words & c_words)
        # 标题权重 + 内容权重 + 额外：标题完整包含 query 短语 bonus
        score = t_overlap * title_weight + c_overlap * 1.0
        # bonus if query phrase appears in title/content (normalized: hyphens -> spaces)
        def _norm_phrase(s: str) -> str:
            return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

        q_norm_phrase = _norm_phrase(query)
        t_norm = _norm_phrase(title)
        c_norm = _norm_phrase(content)
        if q_norm_phrase and q_norm_phrase in t_norm:
            score += 3.0
        elif q_norm_phrase and q_norm_phrase in c_norm:
            score += 1.0
        # domain diversity bonus: prefer wiki/arxiv etc not needed for ranking
        scored.append((score, -idx, r))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [r for _, _, r in scored]


def _fetch_searxng(query: str, num: int) -> list[dict] | None:
    try:
        # bypass proxy for localhost
        proxies = {"http": None, "https": None}
        resp = requests.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json", "categories": "general", "language": "en"},
            timeout=SEARXNG_TIMEOUT,
            headers=HEADERS,
            proxies=proxies,
        )
        if resp.status_code != 200:
            logger.debug("searxng status %s for %s", resp.status_code, query)
            return None
        # try json
        try:
            data = resp.json()
        except Exception:
            logger.debug("searxng non-json for %s: %s", query, resp.text[:500])
            return None
        raw = data.get("results") or data.get("answers") or []
        if not isinstance(raw, list) or not raw:
            return None
        out: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or item.get("name") or "").strip()
            url = (item.get("url") or item.get("link") or "").strip()
            content = (item.get("content") or item.get("snippet") or item.get("description") or "").strip()
            if not url or not title:
                continue
            if not content:
                content = title
            out.append(_with_provenance(title, url, content, "searxng"))
            if len(out) >= num * 2:
                break
        return out if out else None
    except Exception as e:
        logger.debug("searxng fetch fail %s: %s", query, e)
        return None


def _decode_bing_url(href: str) -> str:
    """解码 Bing 的 ck/a?u=  base64 重定向"""
    try:
        parsed = urllib.parse.urlparse(href)
        if "bing.com" in parsed.netloc and "u=" in parsed.query:
            qs = urllib.parse.parse_qs(parsed.query)
            u_vals = qs.get("u")
            if u_vals:
                v = u_vals[0]
                # bing u is base64 with leading 'a1' per observation
                for prefix in ("a1", "a", ""):
                    try:
                        cand = v[len(prefix) :] if v.startswith(prefix) else v
                        # pad base64
                        cand_padded = cand + "=" * (-len(cand) % 4)
                        import base64

                        decoded = base64.b64decode(cand_padded).decode("utf-8", errors="ignore")
                        if decoded.startswith("http"):
                            return decoded
                    except Exception:
                        continue
                # fallback url decode
                return urllib.parse.unquote(v)
    except Exception:
        pass
    return href


def _extract_duckduckgo_url(href: str) -> str:
    href = href.strip()
    if not href:
        return href
    # //duckduckgo etc
    if href.startswith("//"):
        href = "https:" + href
    # contains uddg param (redirect)
    if "uddg=" in href:
        try:
            parsed = urllib.parse.urlparse(href)
            qs = urllib.parse.parse_qs(parsed.query)
            if "uddg" in qs and qs["uddg"]:
                return urllib.parse.unquote(qs["uddg"][0])
            # fallback regex
            m = re.search(r"uddg=([^&]+)", href)
            if m:
                return urllib.parse.unquote(m.group(1))
        except Exception:
            pass
    # Bing decode also applicable for duck? try bing decode
    return _decode_bing_url(href)


def _search_duckduckgo(query: str, num: int) -> list[dict]:
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=HEADERS,
            timeout=SEARCH_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.debug("duckduckgo status %s", resp.status_code)
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        out: list[dict] = []
        # html.duckduckgo uses .result .result__a .result__url .result__snippet
        for r in soup.select(".result"):
            a = r.select_one("a.result__a")
            if not a:
                a = r.find("a", href=True)
            if not a:
                continue
            title = a.get_text(strip=True)
            href = a.get("href", "").strip()
            url = _extract_duckduckgo_url(href)
            # filter out duckduckgo internal
            if not url or "duckduckgo.com" in url or not url.startswith("http"):
                continue
            snippet_el = r.select_one(".result__snippet")
            if not snippet_el:
                snippet_el = r.select_one(".result__extras") or r.find("span")
            content = snippet_el.get_text(" ", strip=True) if snippet_el else ""
            if not content:
                content = title + f" — related to {query}"
            if title and url:
                out.append(_with_provenance(title, url, content, "duckduckgo"))
            if len(out) >= num:
                break
        return out
    except Exception as e:
        logger.debug("duckduckgo fail %s: %s", query, e)
        return []


def _search_bing(query: str, num: int) -> list[dict]:
    try:
        resp = requests.get(
            "https://www.bing.com/search",
            params={"q": query},
            headers=HEADERS,
            timeout=SEARCH_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.debug("bing status %s", resp.status_code)
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        out: list[dict] = []
        for li in soup.select("li.b_algo"):
            h2 = li.find("h2")
            a = h2.find("a", href=True) if h2 else None
            if not a:
                continue
            title = a.get_text(strip=True)
            raw_href = a.get("href", "").strip()
            url = _decode_bing_url(raw_href)
            if not url.startswith("http"):
                continue
            # snippet: b_caption or p
            snippet = li.select_one("p") or li.select_one(".b_caption p") or li.find("div", class_="b_caption")
            if snippet:
                content = snippet.get_text(" ", strip=True)
            else:
                # fallback: text after h2
                content = li.get_text(" ", strip=True).replace(title, "").strip()[:300]
            if not content:
                content = title + f" — {query}"
            if title and url:
                out.append(_with_provenance(title, url, content, "bing"))
            if len(out) >= num:
                break
        return out
    except Exception as e:
        logger.debug("bing fail %s: %s", query, e)
        return []


def _search_brave(query: str, num: int) -> list[dict]:
    key = os.getenv("BRAVE_API_KEY") or os.getenv("BRAVE_SEARCH_API_KEY") or os.getenv("BRAVE_API_TOKEN")
    if not key:
        return []
    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": min(num, 10)},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
            timeout=SEARCH_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.debug("brave status %s", resp.status_code)
            return []
        data = resp.json()
        raw = data.get("web", {}).get("results") or data.get("results") or []
        out: list[dict] = []
        for item in raw:
            title = (item.get("title") or "").strip()
            url = (item.get("url") or "").strip()
            content = (item.get("description") or item.get("snippet") or "").strip()
            if not content:
                content = title
            if title and url:
                out.append(_with_provenance(title, url, content, "brave"))
            if len(out) >= num:
                break
        return out
    except Exception as e:
        logger.debug("brave fail %s: %s", query, e)
        return []


def _site_host(query: str) -> str | None:
    match = re.search(r"(?:^|\s)site:([^\s]+)", query, flags=re.IGNORECASE)
    if not match:
        return None
    host = match.group(1).lower().strip().rstrip("/")
    return host.removeprefix("https://").removeprefix("http://").split("/", 1)[0] or None


def _matches_site(result: dict, host: str | None) -> bool:
    if host is None:
        return True
    candidate_host = urllib.parse.urlparse(str(result.get("url", ""))).hostname
    if not candidate_host:
        return False
    candidate_host = candidate_host.lower()
    return candidate_host == host or candidate_host.endswith(f".{host}")


def _fetch_candidates(query: str, num: int) -> list[dict]:
    try:
        with _native_lifecycle().lease():
            fetched = requests.post(
                f"{SEARCH_FETCHER_URL}/v1/fetch", json={"query": query, "limit": num * 2}, timeout=SEARCH_TIMEOUT
            )
            if fetched.status_code == 503:
                raise SearchUnavailableError("NO_RETRIEVAL_BACKEND: fetcher unavailable")
            fetched.raise_for_status()
            candidates = fetched.json().get("candidates", [])
            ranked = requests.post(
                f"{SEARCH_CORE_URL}/v1/rank", json={"query": query, "limit": num, "candidates": candidates}, timeout=SEARCH_TIMEOUT
            )
            ranked.raise_for_status()
            return [item for item in ranked.json().get("results", []) if _is_provenanced_result(item)]
    except SearchUnavailableError:
        raise
    except SearchLifecycleError as exc:
        raise SearchUnavailableError(f"NO_RETRIEVAL_BACKEND: {exc}") from exc
    except requests.RequestException as exc:
        raise SearchUnavailableError(f"NO_RETRIEVAL_BACKEND: native search services unavailable ({exc})") from exc


def _native_lifecycle():
    return get_search_lifecycle()


def search_web(query: str, num: int = DEFAULT_NUM) -> list[dict]:
    """主入口：兼容 jina search_web(query, num=5)"""
    _validate_query(query)
    if not isinstance(num, int):
        try:
            num = int(num)
        except Exception:
            raise TypeError("num 必须为 int")
    if num <= 0:
        num = DEFAULT_NUM
    if num > 20:
        num = 20

    # 1. 缓存命中
    cached = _read_cache(query)
    if cached is not None:
        # deduplicate already cached (defensive)
        deduped = _dedup_results(cached)
        ranked = _rank_results(deduped, query)
        truncated = ranked[:num]
        # still valid cache
        return truncated

    candidates = _fetch_candidates(query, num)
    if not candidates:
        raise SearchUnavailableError("NO_RETRIEVAL_BACKEND: no backend returned a valid result")

    filtered = [item for item in candidates if _matches_site(item, _site_host(query))]
    if not filtered:
        return []
    ranked = _rank_results(_dedup_results(filtered), query)
    truncated = ranked[:num]
    _write_cache(query, truncated)
    return truncated


def parallel_search_web(queries: list[str], num: int = DEFAULT_NUM) -> list[list[dict]]:
    """并发批量 search_web"""
    if not isinstance(queries, list):
        raise TypeError("queries 必须为 list[str]")
    if not queries:
        return []
    for q in queries:
        _validate_query(q)
    if not isinstance(num, int):
        try:
            num = int(num)
        except Exception:
            raise TypeError("num 必须为 int")
    # ThreadPool并发
    results: list[list[dict] | None] = [None] * len(queries)

    def _task(idx_q):
        idx, q = idx_q
        return idx, search_web(q, num=num)

    max_workers = min(len(queries), 5)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(search_web, q, num): i for i, q in enumerate(queries)}
        for fut in as_completed(futs):
            idx = futs[fut]
            try:
                results[idx] = fut.result()
            except Exception as e:
                # propagate validation errors immediately
                for f in futs:
                    f.cancel()
                raise e
    return [r if r is not None else [] for r in results]
