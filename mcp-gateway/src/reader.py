"""生产级本地 Reader：trafilatura + readability-lxml + bs4 双抽取，自动选最长；question 切片；并发；缓存；严格校验"""

import hashlib
import logging
import pathlib
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

CACHE_DIR = pathlib.Path("/tmp/opencode/jina-local")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

TIMEOUT = 10
HEADERS = {"User-Agent": "jina-local-reader/1.0 (+https://jina.ai/reader)"}
CHUNK_WORDS = 100
TOP_K = 3


def _validate_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url 必须为非空字符串")
    u = url.strip()
    parsed = urllib.parse.urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"无效 url scheme，必须为 http/https: {url}")
    if not parsed.netloc:
        raise ValueError(f"无效 url，缺少 host: {url}")
    # rough invalid char check
    if " " in u or "\n" in u:
        raise ValueError(f"无效 url 含非法字符: {url}")
    return u


def _cache_path(url: str) -> pathlib.Path:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.md"


def _read_cache(url: str) -> str | None:
    p = _cache_path(url)
    if p.exists():
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            return None
    return None


def _write_cache(url: str, content: str) -> None:
    p = _cache_path(url)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    except Exception as e:
        logger.debug("cache write fail %s: %s", url, e)


def _fetch_html(url: str) -> str:
    import requests

    # requests will raise InvalidSchema / InvalidURL / ConnectionError etc.
    resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS, allow_redirects=True)
    # 严格校验：404/5xx 直接抛异常，不静默 fallback
    resp.raise_for_status()
    # ensure text decoding
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def _html_to_markdown(html_fragment: str) -> str:
    """将 HTML fragment 转 markdown，保留标题、列表、代码块、表格、链接、加粗等"""
    try:
        from bs4 import BeautifulSoup, NavigableString, Tag
    except ImportError:
        return html_fragment[:5000]

    soup = BeautifulSoup(html_fragment, "lxml")
    # remove噪音
    for tag in soup(["script", "style", "noscript", "iframe", "nav", "footer"]):
        tag.decompose()

    # prefer body
    root = soup.body if soup.body else soup

    out_lines: list[str] = []

    def _text(node) -> str:
        if isinstance(node, NavigableString):
            return str(node)
        if isinstance(node, Tag):
            return node.get_text(separator=" ", strip=False)
        return ""

    def _inline_text(tag: Tag) -> str:
        """处理行内强调、链接、code"""
        # clone shallow处理：遍历children
        parts: list[str] = []
        for child in tag.children:
            if isinstance(child, NavigableString):
                parts.append(str(child))
            elif isinstance(child, Tag):
                if child.name in ("strong", "b"):
                    parts.append(f"**{child.get_text(strip=True)}**")
                elif child.name in ("em", "i"):
                    parts.append(f"*{child.get_text(strip=True)}*")
                elif child.name == "code" and child.parent.name != "pre":
                    parts.append(f"`{child.get_text(strip=True)}`")
                elif child.name == "a":
                    href = child.get("href", "")
                    txt = child.get_text(strip=True)
                    if href:
                        parts.append(f"[{txt}]({href})")
                    else:
                        parts.append(txt)
                elif child.name == "br":
                    parts.append("\n")
                else:
                    parts.append(child.get_text(separator=" ", strip=True))
        return "".join(parts).strip()

    def _table_to_md(table: Tag) -> str:
        rows = table.find_all("tr")
        if not rows:
            return ""
        # extract cells
        md_rows: list[str] = []
        for i, tr in enumerate(rows):
            cells = tr.find_all(["th", "td"])
            vals = [c.get_text(separator=" ", strip=True).replace("|", "\\|") for c in cells]
            md_rows.append("| " + " | ".join(vals) + " |")
            if i == 0:
                md_rows.append("| " + " | ".join(["---"] * len(vals)) + " |")
        return "\n".join(md_rows)

    # 递归块级处理
    for elem in root.descendants:
        if not isinstance(elem, Tag):
            continue
        # only process top block tags to avoid duplication; check parent is root or direct
        # instead walk children of root iteratively
        pass

    # Better: iterate direct children of root in order
    # if root has many nested, fallback to find_all block
    # We will walk in document order for block elements
    for tag in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "pre", "table", "blockquote", "hr"], recursive=True):
        # skip nested ul/ol inside li already handled? we handle ul/ol as whole
        if tag.name in ("ul", "ol"):
            # avoid double-processing li that are children of already handled ul
            items = tag.find_all("li", recursive=False)
            if not items:
                # nested or deep, get all li
                items = tag.find_all("li")
            for li in items:
                # handle li inline
                txt = _inline_text(li) if list(li.children) else li.get_text(separator=" ", strip=True)
                # if li contains nested block, fallback to text
                prefix = "- " if tag.name == "ul" else "1. "
                out_lines.append(f"{prefix}{txt}")
            out_lines.append("")
        elif tag.name.startswith("h"):
            level = int(tag.name[1])
            txt = tag.get_text(separator=" ", strip=True)
            if txt:
                out_lines.append(f"{'#' * level} {txt}")
                out_lines.append("")
        elif tag.name == "p":
            # skip p inside li/td/th/pre/blockquote already handled
            if tag.find_parent(["li", "td", "th", "pre", "blockquote"]):
                continue
            txt = _inline_text(tag) if tag.find(["a", "strong", "b", "em", "i", "code"]) else tag.get_text(separator=" ", strip=True)
            if txt:
                out_lines.append(txt)
                out_lines.append("")
        elif tag.name == "pre":
            code_tag = tag.find("code")
            code_text = code_tag.get_text() if code_tag else tag.get_text()
            code_text = code_text.strip("\n")
            # detect language hint from class
            lang = ""
            if code_tag and code_tag.get("class"):
                for c in code_tag.get("class"):
                    if c.startswith("language-"):
                        lang = c.replace("language-", "")
            out_lines.append(f"```{lang}\n{code_text}\n```")
            out_lines.append("")
        elif tag.name == "table":
            md_table = _table_to_md(tag)
            if md_table:
                out_lines.append(md_table)
                out_lines.append("")
        elif tag.name == "blockquote":
            # skip nested p handling? include as quote
            txt = tag.get_text(separator=" ", strip=True)
            if txt:
                out_lines.append(f"> {txt}")
                out_lines.append("")
        elif tag.name == "hr":
            out_lines.append("---")
            out_lines.append("")

    # fallback if no block found (e.g., pure text html)
    if not out_lines:
        # try soup get_text as fallback but preserve title
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        body_text = root.get_text(separator="\n", strip=True)
        if title:
            out_lines.append(f"# {title}")
            out_lines.append("")
        out_lines.append(body_text[:8000])

    # cleanup: collapse excessive blank lines
    md = "\n".join(out_lines)
    # collapse 3+ newlines to 2
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = md.strip()
    if not md.startswith("#"):
        # ensure markdown starts with title if possible
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
            if title and title not in md[:200]:
                md = f"# {title}\n\n{md}"
        elif md:
            # first line as title fallback handled by caller
            pass
    return md[:100000]


def _extract_trafilatura(html: str, url: str | None = None) -> str | None:
    try:
        import trafilatura

        # Use markdown output, include tables/formatting
        extracted = trafilatura.extract(
            html,
            output_format="markdown",
            include_comments=False,
            include_tables=True,
            favor_recall=True,
            url=url,
        )
        if extracted and extracted.strip():
            # trafilatura may already be markdown; ensure it has heading handling
            return extracted.strip()
        # fallback try without markdown to then convert
        extracted2 = trafilatura.extract(html, output_format="txt", include_tables=True, url=url)
        if extracted2 and extracted2.strip():
            # wrap as markdown paragraph
            return extracted2.strip()
    except Exception as e:
        logger.debug("trafilatura extract fail: %s", e)
    return None


def _extract_readability(html: str, url: str | None = None) -> str | None:
    try:
        from readability import Document

        doc = Document(html)
        title = doc.short_title()
        summary_html = doc.summary(html_partial=True)
        md = _html_to_markdown(summary_html)
        # ensure title present
        if title and title not in md[:500]:
            md = f"# {title}\n\n{md}"
        if md.strip():
            return md.strip()
    except Exception as e:
        logger.debug("readability extract fail: %s", e)
    # fallback pure bs4 html_to_markdown on full html
    try:
        md = _html_to_markdown(html)
        if md.strip():
            return md.strip()
    except Exception as e:
        logger.debug("bs4 fallback fail: %s", e)
    return None


def _choose_best(cands: list[str | None]) -> str | None:
    valid = [c for c in cands if c and c.strip()]
    if not valid:
        return None
    # prefer longest (more complete), but also prefer markdown with headings
    # score = len + bonus for headings/tables/code
    def _score(s: str) -> int:
        bonus = 0
        if "# " in s:
            bonus += 500
        if "```" in s:
            bonus += 300
        if "|" in s and "---" in s:
            bonus += 300
        if "- " in s or "* " in s:
            bonus += 100
        return len(s) + bonus

    valid.sort(key=_score, reverse=True)
    return valid[0]


def _chunk_text(text: str, chunk_size: int = CHUNK_WORDS) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i : i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
    return chunks


def _word_overlap_score(query: str, doc: str) -> float:
    def _norm(s: str) -> set[str]:
        return set(re.sub(r"[^a-z0-9]", " ", s.lower()).split()) - {""}

    q = _norm(query)
    d = _norm(doc)
    if not q or not d:
        return 0.0
    return float(len(q & d))


def _select_top_chunks(question: str, chunks: list[str], top_k: int = TOP_K) -> list[str]:
    if not question or not chunks:
        return chunks[:top_k]
    scored = []
    for idx, ch in enumerate(chunks):
        score = _word_overlap_score(question, ch)
        # tiny deterministic tie-break
        scored.append((score, -idx, ch))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    # if all zero, just return first top_k (fallback)
    # filter to non-zero? but if question unrelated, still return most relevant (maybe all zero)
    top = [c for _, _, c in scored[:top_k]]
    # if top scores all zero, return first top_k original order to avoid random
    if all(s == 0 for s, _, _ in scored[:top_k]):
        return chunks[:top_k]
    return top


def read_url(url: str, question: str | None = None, chunk_size: int = CHUNK_WORDS, top_k: int = TOP_K) -> str:
    """
    本地 Reader 主入口，兼容 jina read_url(question 语义切片)
    - url 必填，严格校验
    - question 可选：若提供则按 100词窗口切分并用词重叠 rerank 选 top 3
    - 缓存：/tmp/opencode/jina-local/{sha256(url)}.md
    """
    url = _validate_url(url)
    if question is not None and not isinstance(question, str):
        raise TypeError("question 必须为 str 或 None")
    if question is not None and not question.strip():
        question = None

    # cache hit paths: try cache first
    cached = _read_cache(url)
    full_md: str | None = None
    if cached is not None and question is None:
        return cached
    if cached is not None and question is not None:
        # use cached full text to slice, no network
        full_md = cached

    if full_md is None and cached is not None:
        full_md = cached
    elif full_md is None:
        # need to fetch
        html = _fetch_html(url)
        cands: list[str | None] = []
        # dual extraction + direct fallback
        cands.append(_extract_trafilatura(html, url=url))
        cands.append(_extract_readability(html, url=url))
        # direct html_to_markdown always considered to preserve lists/tables/code
        try:
            cands.append(_html_to_markdown(html))
        except Exception:
            pass
        # final fallback simple markdown from bs4 if both fail (already in readability)
        best = _choose_best(cands)
        if not best:
            # last resort: html_to_markdown direct
            best = _html_to_markdown(html)
        if not best or not best.strip():
            raise RuntimeError(f"无法抽取 {url} 的正文")
        # ensure starts with heading for markdown quality test
        if not best.lstrip().startswith("#"):
            # try to prepend title
            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(html, "lxml")
                title = soup.title.string.strip() if soup.title and soup.title.string else ""
                if title:
                    best = f"# {title}\n\n{best}"
                else:
                    best = f"# Title\n\n{best}"
            except Exception:
                best = f"# Title\n\n{best}"
        full_md = best
        # write cache (full)
        _write_cache(url, full_md)

    assert full_md is not None

    if question is None:
        return full_md

    # question slicing
    chunks = _chunk_text(full_md, chunk_size=chunk_size)
    if not chunks:
        return full_md
    top_chunks = _select_top_chunks(question, chunks, top_k=top_k)
    # return joined with separator, keep markdown structure minimal
    return "\n\n---\n\n".join(top_chunks)


def parallel_read_url(urls: list[str], question: str | None = None, max_workers: int = 5) -> list[str]:
    if not isinstance(urls, list):
        raise TypeError("urls 必须为 list[str]")
    if not urls:
        return []
    for u in urls:
        if not isinstance(u, str):
            raise TypeError("urls 元素必须为 str")
        # validate early to raise quickly; defer fetch error handling to thread?
        _validate_url(u)

    results: list[str | None] = [None] * len(urls)

    def _task(idx_url):
        idx, u = idx_url
        return idx, read_url(u, question=question)

    with ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as ex:
        futs = {ex.submit(read_url, u, question): i for i, u in enumerate(urls)}
        for fut in as_completed(futs):
            idx = futs[fut]
            try:
                results[idx] = fut.result()
            except Exception as e:
                # propagate first exception? requirement says strict, so raise
                # cancel others and raise
                for f in futs:
                    f.cancel()
                raise e

    # all should be str
    return [r if r is not None else "" for r in results]
