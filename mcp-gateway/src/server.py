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
        read_url,
        parallel_read_url,
        search_web,
        sort_by_relevance,
        parallel_search_web,
        search_web_deep,
        deduplicate_strings,
        deduplicate_images,
        classify_text,
        expand_query,
        extract_pdf,
        guess_datetime_url,
        primer,
        search_arxiv,
        parallel_search_arxiv,
        search_ssrn,
        parallel_search_ssrn,
        search_bibtex,
        search_images,
        search_jina_blog,
        capture_screenshot_url,
        embeddings,
    )
except ImportError:
    try:
        from gateway import read_url, parallel_read_url, search_web, sort_by_relevance, parallel_search_web, search_web_deep, deduplicate_strings, deduplicate_images, classify_text, expand_query, extract_pdf, guess_datetime_url, primer, search_arxiv, parallel_search_arxiv, search_ssrn, parallel_search_ssrn, search_bibtex, search_images, search_jina_blog, capture_screenshot_url, embeddings  # type: ignore
    except ImportError:  # fallback for direct file execution without package context
        import importlib.util
        import pathlib as _pl

        _gw_path = _pl.Path(__file__).with_name("gateway.py")
        _spec = importlib.util.spec_from_file_location("gateway", _gw_path)
        assert _spec and _spec.loader
        _gw = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_gw)  # type: ignore
        read_url = _gw.read_url  # type: ignore
        parallel_read_url = getattr(_gw, "parallel_read_url", None)  # type: ignore
        search_web = _gw.search_web  # type: ignore
        sort_by_relevance = _gw.sort_by_relevance  # type: ignore
        parallel_search_web = getattr(_gw, "parallel_search_web", None)  # type: ignore
        search_web_deep = getattr(_gw, "search_web_deep", None)  # type: ignore
        deduplicate_strings = getattr(_gw, "deduplicate_strings", None)  # type: ignore
        deduplicate_images = getattr(_gw, "deduplicate_images", None)  # type: ignore
        classify_text = getattr(_gw, "classify_text", None)  # type: ignore
        expand_query = getattr(_gw, "expand_query", None)  # type: ignore
        extract_pdf = getattr(_gw, "extract_pdf", None)  # type: ignore
        guess_datetime_url = getattr(_gw, "guess_datetime_url", None)  # type: ignore
        primer = getattr(_gw, "primer", None)  # type: ignore
        search_arxiv = getattr(_gw, "search_arxiv", None)  # type: ignore
        parallel_search_arxiv = getattr(_gw, "parallel_search_arxiv", None)  # type: ignore
        search_ssrn = getattr(_gw, "search_ssrn", None)  # type: ignore
        parallel_search_ssrn = getattr(_gw, "parallel_search_ssrn", None)  # type: ignore
        search_bibtex = getattr(_gw, "search_bibtex", None)  # type: ignore
        search_images = getattr(_gw, "search_images", None)  # type: ignore
        search_jina_blog = getattr(_gw, "search_jina_blog", None)  # type: ignore
        capture_screenshot_url = getattr(_gw, "capture_screenshot_url", None)  # type: ignore
        embeddings = getattr(_gw, "embeddings", None)  # type: ignore
        if parallel_read_url is None:
            try:
                from reader import parallel_read_url as parallel_read_url  # type: ignore
            except ImportError:
                parallel_read_url = None  # type: ignore
        if parallel_search_web is None:
            try:
                from search import parallel_search_web as parallel_search_web  # type: ignore
            except ImportError:
                parallel_search_web = None  # type: ignore
        if search_web_deep is None:
            try:
                from search_deep import search_web_deep as search_web_deep  # type: ignore
            except ImportError:
                search_web_deep = None  # type: ignore
        # fallback for academic utils
        for _name in ["search_arxiv", "parallel_search_arxiv", "search_ssrn", "parallel_search_ssrn", "search_bibtex", "search_images", "search_jina_blog", "capture_screenshot_url"]:
            if locals().get(_name) is None:
                try:
                    import importlib as _imp
                    _sa = _imp.import_module("search_academic")
                    locals()[_name] = getattr(_sa, _name, None)
                except Exception:
                    try:
                        import pathlib as _p2
                        _sa_path = _p2.Path(__file__).with_name("search_academic.py")
                        if _sa_path.exists():
                            _spec2 = importlib.util.spec_from_file_location("search_academic", _sa_path)
                            assert _spec2 and _spec2.loader
                            _mod2 = importlib.util.module_from_spec(_spec2)
                            _spec2.loader.exec_module(_mod2)  # type: ignore
                            locals()[_name] = getattr(_mod2, _name, None)
                    except Exception:
                        pass

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
    def embeddings_tool(texts: list[str]) -> list[list[float]]:
        return embeddings(texts)

    @mcp.tool()
    def read_url_tool(url: str) -> str:
        """Fetch URL and return markdown string (wrapper over gateway.read_url)."""
        return read_url(url)

    @mcp.tool()
    def parallel_read_url_tool(urls: list[str]) -> list[str]:
        return parallel_read_url(urls)

    @mcp.tool()
    def search_web_tool(query: str, num: int = 5) -> list[dict]:
        """Search web wrapper over gateway.search_web."""
        return search_web(query, num=num)

    @mcp.tool()
    def parallel_search_web_tool(queries: list[str], num: int = 5) -> list[list[dict]]:
        """Parallel search wrapper over gateway.parallel_search_web."""
        return parallel_search_web(queries, num=num)

    @mcp.tool()
    def sort_by_relevance_tool(query: str, documents: list[str]) -> list[dict]:
        """Rerank wrapper over gateway.sort_by_relevance."""
        return sort_by_relevance(query, documents)

    @mcp.tool()
    def search_web_deep_tool(query: str, num: int = 5, chunk_size: int = 100) -> list[dict]:
        """Search deep wrapper over gateway.search_web_deep."""
        return search_web_deep(query, num=num, chunk_size=chunk_size)

    @mcp.tool()
    def deduplicate_strings_tool(strings: list[str], top_k: int | None = None) -> list[str]:
        return deduplicate_strings(strings, top_k=top_k)

    @mcp.tool()
    def deduplicate_images_tool(images: list[str], top_k: int | None = None) -> list[str]:
        return deduplicate_images(images, top_k=top_k)

    @mcp.tool()
    def classify_text_tool(texts: list[str], labels: list[str]) -> list[dict]:
        return classify_text(texts, labels)

    @mcp.tool()
    def expand_query_tool(query: str, num: int = 3) -> list[str]:
        return expand_query(query, num=num)

    @mcp.tool()
    def extract_pdf_tool(url: str) -> dict:
        return extract_pdf(url)

    @mcp.tool()
    def guess_datetime_url_tool(url: str) -> dict:
        return guess_datetime_url(url)

    @mcp.tool()
    def primer_tool() -> dict:
        return primer()

    @mcp.tool()
    def search_arxiv_tool(query: str, num: int = 5) -> list[dict]:
        return search_arxiv(query, num=num)

    @mcp.tool()
    def parallel_search_arxiv_tool(queries: list[str], num: int = 5) -> list[list[dict]]:
        return parallel_search_arxiv(queries, num=num)

    @mcp.tool()
    def search_ssrn_tool(query: str, num: int = 5) -> list[dict]:
        return search_ssrn(query, num=num)

    @mcp.tool()
    def parallel_search_ssrn_tool(queries: list[str], num: int = 5) -> list[list[dict]]:
        return parallel_search_ssrn(queries, num=num)

    @mcp.tool()
    def search_bibtex_tool(query: str, num: int = 5) -> list[dict]:
        return search_bibtex(query, num=num)

    @mcp.tool()
    def search_images_tool(query: str, num: int = 5) -> list[dict]:
        return search_images(query, num=num)

    @mcp.tool()
    def search_jina_blog_tool(query: str, num: int = 5) -> list[dict]:
        return search_jina_blog(query, num=num)

    @mcp.tool()
    def capture_screenshot_url_tool(url: str) -> dict:
        return capture_screenshot_url(url)

    # 同时直接暴露原始函数名以兼容 jina 工具名（21工具）
    mcp.tool()(read_url)
    mcp.tool()(parallel_read_url)
    mcp.tool()(search_web)
    mcp.tool()(parallel_search_web)
    mcp.tool()(sort_by_relevance)
    mcp.tool()(search_web_deep)
    mcp.tool()(deduplicate_strings)
    mcp.tool()(deduplicate_images)
    mcp.tool()(classify_text)
    mcp.tool()(expand_query)
    mcp.tool()(extract_pdf)
    mcp.tool()(guess_datetime_url)
    mcp.tool()(primer)
    mcp.tool()(search_arxiv)
    mcp.tool()(parallel_search_arxiv)
    mcp.tool()(search_ssrn)
    mcp.tool()(parallel_search_ssrn)
    mcp.tool()(search_bibtex)
    mcp.tool()(search_images)
    mcp.tool()(search_jina_blog)
    mcp.tool()(capture_screenshot_url)

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
            # 若为未知 transport 或其他可重试错误，尝试 uvicorn 包装
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
        "read_url", "parallel_read_url", "search_web", "sort_by_relevance", "search_web_deep",
        "deduplicate_strings", "deduplicate_images", "classify_text", "expand_query", "extract_pdf",
        "guess_datetime_url", "primer", "search_arxiv", "parallel_search_arxiv", "search_ssrn",
        "parallel_search_ssrn", "search_bibtex", "search_images", "search_jina_blog",
        "capture_screenshot_url", "embeddings_tool", "mcp", "main", "_parse_args",
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

    # 保留原始函数可直接调用
    __all__ = [
        "read_url", "parallel_read_url", "search_web", "sort_by_relevance", "search_web_deep",
        "deduplicate_strings", "deduplicate_images", "classify_text", "expand_query", "extract_pdf",
        "guess_datetime_url", "primer", "search_arxiv", "parallel_search_arxiv", "search_ssrn",
        "parallel_search_ssrn", "search_bibtex", "search_images", "search_jina_blog",
        "capture_screenshot_url", "mcp", "main", "_parse_args",
        "SUPPORTED_TRANSPORTS", "TRANSPORT_CHOICES", "AVAILABLE_TRANSPORTS", "TRANSPORT_ALIASES",
        "DEFAULT_TRANSPORT", "DEFAULT_HOST", "DEFAULT_PORT",
    ]
