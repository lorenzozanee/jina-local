"""FastMCP stdio 入口，复用 gateway.py 三函数。"""

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as _e:  # pragma: no cover
    FastMCP = None  # type: ignore

try:
    from .gateway import read_url, search_web, sort_by_relevance, parallel_search_web, search_web_deep
except ImportError:
    try:
        from gateway import read_url, search_web, sort_by_relevance, parallel_search_web, search_web_deep  # type: ignore
    except ImportError:  # fallback for direct file execution without package context
        import importlib.util
        import pathlib as _pl

        _gw_path = _pl.Path(__file__).with_name("gateway.py")
        _spec = importlib.util.spec_from_file_location("gateway", _gw_path)
        assert _spec and _spec.loader
        _gw = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_gw)  # type: ignore
        read_url = _gw.read_url  # type: ignore
        search_web = _gw.search_web  # type: ignore
        sort_by_relevance = _gw.sort_by_relevance  # type: ignore
        parallel_search_web = getattr(_gw, "parallel_search_web", None)  # type: ignore
        search_web_deep = getattr(_gw, "search_web_deep", None)  # type: ignore
        if parallel_search_web is None:
            # fallback via search module
            try:
                from search import parallel_search_web as parallel_search_web  # type: ignore
            except ImportError:
                parallel_search_web = None  # type: ignore
        if search_web_deep is None:
            try:
                from search_deep import search_web_deep as search_web_deep  # type: ignore
            except ImportError:
                search_web_deep = None  # type: ignore

if FastMCP is not None:
    mcp = FastMCP("jina-local-gateway")

    @mcp.tool()
    def read_url_tool(url: str) -> str:
        """Fetch URL and return markdown string (wrapper over gateway.read_url)."""
        return read_url(url)

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

    # 同时直接暴露原始函数名以兼容 jina 工具名
    mcp.tool()(read_url)
    mcp.tool()(search_web)
    mcp.tool()(parallel_search_web)
    mcp.tool()(sort_by_relevance)
    mcp.tool()(search_web_deep)

    def main() -> None:
        mcp.run()

    if __name__ == "__main__":
        main()
else:  # fallback when mcp not installed
    mcp = None  # type: ignore

    def main() -> None:  # pragma: no cover
        raise RuntimeError("mcp>=1.0 未安装，无法启动 FastMCP server，请先 pip install mcp")

    # 保留原始函数可直接调用
    __all__ = ["read_url", "search_web", "sort_by_relevance", "search_web_deep", "mcp", "main"]
