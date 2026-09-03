"""FastMCP 多传输入口，复用 gateway.py 全部 20+1 工具。

支持传输：
  python server.py --transport stdio --port 3000 --host 0.0.0.0  # stdio 默认
  python server.py --transport sse --port 3000 --host 0.0.0.0
  python server.py --transport http --port 3000 --host 0.0.0.0  # http -> streamable-http
"""

import argparse
import sys

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as _e:  # pragma: no cover
    FastMCP = None  # type: ignore

try:
    from .gateway import (
        read_url as _read_url_impl,
        parallel_read_url as _parallel_read_url_impl,
        search_web as _search_web_impl,
        sort_by_relevance as _sort_by_relevance_impl,
        parallel_search_web as _parallel_search_web_impl,
        search_web_deep as _search_web_deep_impl,
        deduplicate_strings as _deduplicate_strings_impl,
        deduplicate_images as _deduplicate_images_impl,
        classify_text as _classify_text_impl,
        expand_query as _expand_query_impl,
        extract_pdf as _extract_pdf_impl,
        guess_datetime_url as _guess_datetime_url_impl,
        primer as _primer_impl,
        search_arxiv as _search_arxiv_impl,
        parallel_search_arxiv as _parallel_search_arxiv_impl,
        search_ssrn as _search_ssrn_impl,
        parallel_search_ssrn as _parallel_search_ssrn_impl,
        search_bibtex as _search_bibtex_impl,
        search_images as _search_images_impl,
        search_jina_blog as _search_jina_blog_impl,
        capture_screenshot_url as _capture_screenshot_url_impl,
        embeddings as _embeddings_impl,
    )
except ImportError:
    try:
        from gateway import (
            read_url as _read_url_impl,
            parallel_read_url as _parallel_read_url_impl,
            search_web as _search_web_impl,
            sort_by_relevance as _sort_by_relevance_impl,
            parallel_search_web as _parallel_search_web_impl,
            search_web_deep as _search_web_deep_impl,
            deduplicate_strings as _deduplicate_strings_impl,
            deduplicate_images as _deduplicate_images_impl,
            classify_text as _classify_text_impl,
            expand_query as _expand_query_impl,
            extract_pdf as _extract_pdf_impl,
            guess_datetime_url as _guess_datetime_url_impl,
            primer as _primer_impl,
            search_arxiv as _search_arxiv_impl,
            parallel_search_arxiv as _parallel_search_arxiv_impl,
            search_ssrn as _search_ssrn_impl,
            parallel_search_ssrn as _parallel_search_ssrn_impl,
            search_bibtex as _search_bibtex_impl,
            search_images as _search_images_impl,
            search_jina_blog as _search_jina_blog_impl,
            capture_screenshot_url as _capture_screenshot_url_impl,
            embeddings as _embeddings_impl,
        )  # type: ignore
    except ImportError:  # fallback for direct file execution without package context
        import importlib.util
        import pathlib as _pl

        _gw_path = _pl.Path(__file__).with_name("gateway.py")
        _spec = importlib.util.spec_from_file_location("gateway", _gw_path)
        assert _spec and _spec.loader
        _gw = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_gw)  # type: ignore
        _read_url_impl = getattr(_gw, "read_url", None)  # type: ignore
        _parallel_read_url_impl = getattr(_gw, "parallel_read_url", None)  # type: ignore
        _search_web_impl = getattr(_gw, "search_web", None)  # type: ignore
        _sort_by_relevance_impl = getattr(_gw, "sort_by_relevance", None)  # type: ignore
        _parallel_search_web_impl = getattr(_gw, "parallel_search_web", None)  # type: ignore
        _search_web_deep_impl = getattr(_gw, "search_web_deep", None)  # type: ignore
        _deduplicate_strings_impl = getattr(_gw, "deduplicate_strings", None)  # type: ignore
        _deduplicate_images_impl = getattr(_gw, "deduplicate_images", None)  # type: ignore
        _classify_text_impl = getattr(_gw, "classify_text", None)  # type: ignore
        _expand_query_impl = getattr(_gw, "expand_query", None)  # type: ignore
        _extract_pdf_impl = getattr(_gw, "extract_pdf", None)  # type: ignore
        _guess_datetime_url_impl = getattr(_gw, "guess_datetime_url", None)  # type: ignore
        _primer_impl = getattr(_gw, "primer", None)  # type: ignore
        _search_arxiv_impl = getattr(_gw, "search_arxiv", None)  # type: ignore
        _parallel_search_arxiv_impl = getattr(_gw, "parallel_search_arxiv", None)  # type: ignore
        _search_ssrn_impl = getattr(_gw, "search_ssrn", None)  # type: ignore
        _parallel_search_ssrn_impl = getattr(_gw, "parallel_search_ssrn", None)  # type: ignore
        _search_bibtex_impl = getattr(_gw, "search_bibtex", None)  # type: ignore
        _search_images_impl = getattr(_gw, "search_images", None)  # type: ignore
        _search_jina_blog_impl = getattr(_gw, "search_jina_blog", None)  # type: ignore
        _capture_screenshot_url_impl = getattr(_gw, "capture_screenshot_url", None)  # type: ignore
        _embeddings_impl = getattr(_gw, "embeddings", None)  # type: ignore
        if _parallel_read_url_impl is None:
            try:
                from reader import parallel_read_url as parallel_read_url  # type: ignore
                _parallel_read_url_impl = parallel_read_url  # type: ignore
            except ImportError:
                _parallel_read_url_impl = None  # type: ignore
        if _parallel_search_web_impl is None:
            try:
                from search import parallel_search_web as parallel_search_web  # type: ignore
                _parallel_search_web_impl = parallel_search_web  # type: ignore
            except ImportError:
                _parallel_search_web_impl = None  # type: ignore
        if _search_web_deep_impl is None:
            try:
                from search_deep import search_web_deep as search_web_deep  # type: ignore
                _search_web_deep_impl = search_web_deep  # type: ignore
            except ImportError:
                _search_web_deep_impl = None  # type: ignore
        # fallback for academic utils
        _academic_names = {
            "search_arxiv": _search_arxiv_impl,
            "parallel_search_arxiv": _parallel_search_arxiv_impl,
            "search_ssrn": _search_ssrn_impl,
            "parallel_search_ssrn": _parallel_search_ssrn_impl,
            "search_bibtex": _search_bibtex_impl,
            "search_images": _search_images_impl,
            "search_jina_blog": _search_jina_blog_impl,
            "capture_screenshot_url": _capture_screenshot_url_impl,
        }
        for _name in _academic_names:
            if _academic_names[_name] is None:
                try:
                    import importlib as _imp
                    _sa = _imp.import_module("search_academic")
                    _academic_names[_name] = getattr(_sa, _name, None)
                except Exception:
                    try:
                        import pathlib as _p2
                        _sa_path = _p2.Path(__file__).with_name("search_academic.py")
                        if _sa_path.exists():
                            _spec2 = importlib.util.spec_from_file_location("search_academic", _sa_path)
                            assert _spec2 and _spec2.loader
                            _mod2 = importlib.util.module_from_spec(_spec2)
                            _spec2.loader.exec_module(_mod2)  # type: ignore
                            _academic_names[_name] = getattr(_mod2, _name, None)
                    except Exception:
                        pass
        _search_arxiv_impl = _academic_names["search_arxiv"]  # type: ignore
        _parallel_search_arxiv_impl = _academic_names["parallel_search_arxiv"]  # type: ignore
        _search_ssrn_impl = _academic_names["search_ssrn"]  # type: ignore
        _parallel_search_ssrn_impl = _academic_names["parallel_search_ssrn"]  # type: ignore
        _search_bibtex_impl = _academic_names["search_bibtex"]  # type: ignore
        _search_images_impl = _academic_names["search_images"]  # type: ignore
        _search_jina_blog_impl = _academic_names["search_jina_blog"]  # type: ignore
        _capture_screenshot_url_impl = _academic_names["capture_screenshot_url"]  # type: ignore

# 传输选项常量，暴露给 __all__ 与 --help
SUPPORTED_TRANSPORTS = ["stdio", "sse", "http", "streamable-http"]
TRANSPORT_CHOICES = SUPPORTED_TRANSPORTS
AVAILABLE_TRANSPORTS = SUPPORTED_TRANSPORTS
TRANSPORT_ALIASES = {"http": "streamable-http", "streamable-http": "streamable-http", "sse": "sse", "stdio": "stdio"}
DEFAULT_TRANSPORT = "stdio"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3000

if FastMCP is not None:
    mcp = FastMCP("jina-local-gateway")

    @mcp.tool()
    def primer() -> dict:
        return _primer_impl()

    @mcp.tool()
    def read_url(url: str, question: str | None = None, chunk_size: int = 100, top_k: int = 3) -> str:
        return _read_url_impl(url, question=question, chunk_size=chunk_size, top_k=top_k)

    @mcp.tool()
    def capture_screenshot_url(url: str) -> dict:
        return _capture_screenshot_url_impl(url)

    @mcp.tool()
    def guess_datetime_url(url: str) -> dict:
        return _guess_datetime_url_impl(url)

    @mcp.tool()
    def search_web(query: str, num: int = 5) -> list[dict]:
        return _search_web_impl(query, num=num)

    @mcp.tool()
    def search_web_deep(query: str, num: int = 5, chunk_size: int = 100) -> list[dict]:
        return _search_web_deep_impl(query, num=num, chunk_size=chunk_size)

    @mcp.tool()
    def search_arxiv(query: str, num: int = 5) -> list[dict]:
        return _search_arxiv_impl(query, num=num)

    @mcp.tool()
    def search_ssrn(query: str, num: int = 5) -> list[dict]:
        return _search_ssrn_impl(query, num=num)

    @mcp.tool()
    def search_images(query: str, num: int = 5) -> list[dict]:
        return _search_images_impl(query, num=num)

    @mcp.tool()
    def search_jina_blog(query: str, num: int = 5) -> list[dict]:
        return _search_jina_blog_impl(query, num=num)

    @mcp.tool()
    def search_bibtex(query: str, num: int = 5) -> list[dict]:
        return _search_bibtex_impl(query, num=num)

    @mcp.tool()
    def expand_query(query: str, num: int = 3) -> list[str]:
        return _expand_query_impl(query, num=num)

    @mcp.tool()
    def parallel_read_url(urls: list[str], question: str | None = None, max_workers: int = 5) -> list[str]:
        return _parallel_read_url_impl(urls, question=question, max_workers=max_workers)

    @mcp.tool()
    def parallel_search_web(queries: list[str], num: int = 5) -> list[list[dict]]:
        return _parallel_search_web_impl(queries, num=num)

    @mcp.tool()
    def parallel_search_arxiv(queries: list[str], num: int = 5) -> list[list[dict]]:
        return _parallel_search_arxiv_impl(queries, num=num)

    @mcp.tool()
    def parallel_search_ssrn(queries: list[str], num: int = 5) -> list[list[dict]]:
        return _parallel_search_ssrn_impl(queries, num=num)

    @mcp.tool()
    def sort_by_relevance(query: str, documents: list[str]) -> list[dict]:
        return _sort_by_relevance_impl(query, documents)

    @mcp.tool()
    def classify_text(texts: list[str], labels: list[str]) -> list[dict]:
        return _classify_text_impl(texts, labels)

    @mcp.tool()
    def deduplicate_strings(strings: list[str], top_k: int | None = None) -> list[str]:
        return _deduplicate_strings_impl(strings, top_k=top_k)

    @mcp.tool()
    def deduplicate_images(images: list[str], top_k: int | None = None) -> list[str]:
        return _deduplicate_images_impl(images, top_k=top_k)

    @mcp.tool()
    def extract_pdf(url: str) -> dict:
        return _extract_pdf_impl(url)

    @mcp.tool()
    def embeddings(texts: list[str]) -> list[list[float]]:
        return _embeddings_impl(texts)

    def _parse_args(argv=None):
        parser = argparse.ArgumentParser(description="jina-local MCP Gateway - FastMCP stdio/sse/http")
        parser.add_argument("--transport", choices=SUPPORTED_TRANSPORTS, default=DEFAULT_TRANSPORT, help="传输模式 (default: stdio)")
        parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="sse/http 监听端口 (default: 3000, 1-65535)")
        parser.add_argument("--host", default=DEFAULT_HOST, help="sse/http 监听地址 (default: 127.0.0.1, 0.0.0.0 对外暴露)")
        args = parser.parse_args(argv)
        if not (1 <= args.port <= 65535):
            parser.error("port 必须在 1-65535 之间")
        return args

    def main(transport: str = DEFAULT_TRANSPORT, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        t_raw = (transport or DEFAULT_TRANSPORT).lower()
        t = TRANSPORT_ALIASES.get(t_raw, t_raw)
        # 兼容 http 别名
        if t not in ("stdio", "sse", "streamable-http"):
            print(f"Unsupported transport '{transport}', supported: {SUPPORTED_TRANSPORTS}", file=sys.stderr)
            sys.exit(1)
        if not (1 <= port <= 65535):
            print(f"port 必须在 1-65535 之间, 实际 {port}", file=sys.stderr)
            sys.exit(1)
        if t == "stdio":
            mcp.run(transport="stdio")
            return
        # sse / streamable-http 需要 host/port
        try:
            mcp.settings.host = host
            mcp.settings.port = port
        except Exception:
            pass
        # 优先使用 FastMCP 原生 transport
        try:
            mcp.run(transport=t)
            return
        except Exception as e:
            msg = str(e).lower()
            # 若为 unknown transport 或其他可重试错误，尝试 uvicorn 包装
            print(f"FastMCP native {t} failed: {e}, trying uvicorn wrapper...", file=sys.stderr)
            try:
                import uvicorn  # type: ignore
            except ImportError:
                print("uvicorn 未安装，无法启动 sse/http 模式，请 pip install uvicorn (已随 mcp 安装) 或升级 mcp", file=sys.stderr)
                print(f"提示: mcp.run(transport='{t}') 不可用，已优雅降级提示", file=sys.stderr)
                sys.exit(1)
            try:
                if t == "sse":
                    app = mcp.sse_app()
                else:
                    app = mcp.streamable_http_app()
                uvicorn.run(app, host=host, port=port)
                return
            except Exception as e2:
                print(f"uvicorn wrapper failed for {t}: {e2}", file=sys.stderr)
                sys.exit(1)

    if __name__ == "__main__":
        _args = _parse_args()
        main(transport=_args.transport, host=_args.host, port=_args.port)

    __all__ = [
        "primer", "read_url", "capture_screenshot_url", "guess_datetime_url",
        "search_web", "search_web_deep",
        "search_arxiv", "search_ssrn", "search_images", "search_jina_blog",
        "search_bibtex", "expand_query",
        "parallel_read_url", "parallel_search_web", "parallel_search_arxiv", "parallel_search_ssrn",
        "sort_by_relevance", "classify_text", "deduplicate_strings", "deduplicate_images",
        "extract_pdf", "embeddings",
        "mcp", "main", "_parse_args",
        "SUPPORTED_TRANSPORTS", "TRANSPORT_CHOICES", "AVAILABLE_TRANSPORTS", "TRANSPORT_ALIASES",
        "DEFAULT_TRANSPORT", "DEFAULT_HOST", "DEFAULT_PORT",
    ]
else:  # fallback when mcp not installed
    mcp = None  # type: ignore

    SUPPORTED_TRANSPORTS = ["stdio", "sse", "http", "streamable-http"]
    TRANSPORT_CHOICES = SUPPORTED_TRANSPORTS
    AVAILABLE_TRANSPORTS = SUPPORTED_TRANSPORTS
    TRANSPORT_ALIASES = {"http": "streamable-http", "streamable-http": "streamable-http", "sse": "sse", "stdio": "stdio"}
    DEFAULT_TRANSPORT = "stdio"
    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 3000

    def _parse_args(argv=None):  # pragma: no cover
        parser = argparse.ArgumentParser(description="jina-local MCP Gateway - FastMCP stdio/sse/http (mcp 未安装)")
        parser.add_argument("--transport", choices=SUPPORTED_TRANSPORTS, default=DEFAULT_TRANSPORT, help="传输模式 (default: stdio)")
        parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="sse/http 监听端口 (default: 3000, 1-65535)")
        parser.add_argument("--host", default=DEFAULT_HOST, help="sse/http 监听地址 (default: 127.0.0.1, 0.0.0.0 对外暴露)")
        return parser.parse_args(argv)

    def main(transport: str = DEFAULT_TRANSPORT, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:  # pragma: no cover
        raise RuntimeError("mcp>=1.0 未安装，无法启动 FastMCP server，请先 pip install mcp")

    if __name__ == "__main__":  # pragma: no cover
        _args = _parse_args()
        main(transport=_args.transport, host=_args.host, port=_args.port)

    __all__ = [
        "primer", "read_url", "capture_screenshot_url", "guess_datetime_url",
        "search_web", "search_web_deep",
        "search_arxiv", "search_ssrn", "search_images", "search_jina_blog",
        "search_bibtex", "expand_query",
        "parallel_read_url", "parallel_search_web", "parallel_search_arxiv", "parallel_search_ssrn",
        "sort_by_relevance", "classify_text", "deduplicate_strings", "deduplicate_images",
        "extract_pdf", "embeddings",
        "mcp", "main", "_parse_args",
        "SUPPORTED_TRANSPORTS", "TRANSPORT_CHOICES", "AVAILABLE_TRANSPORTS", "TRANSPORT_ALIASES",
        "DEFAULT_TRANSPORT", "DEFAULT_HOST", "DEFAULT_PORT",
    ]