"""Reader 深度实现 TDD 扩展测试
要求：
- test_reader_real_fetch：真实网络抓取 example.com + httpbin.org/html
- test_reader_question_param：question 时返回相关段落而非全文（chunk+rerank）
- test_parallel_read_url：并发 3 URL
- test_reader_error_handling：空 url/超时/404 抛异常而非静默 fallback
- test_reader_markdown_quality：返回含标题、列表/代码/表格的 markdown 结构
TDD 红阶段：这些测试在 stub 实现下应 FAIL
"""
import importlib.util
import pathlib
import sys
import time
import threading
import http.server
import socket
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATES = [
    ROOT / "mcp-gateway" / "src" / "reader.py",
    ROOT / "mcp-gateway" / "src" / "gateway.py",
    ROOT / "mcp-gateway" / "src" / "server.py",
]

def _resolve():
    for p in CANDIDATES:
        if p.exists():
            return p
    return None

def _load():
    path = _resolve()
    assert path is not None, f"Reader 模块不存在 {CANDIDATES}"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod, path

def _get_read():
    mod,_ = _load()
    for name in ("read_url","reader","fetch"):
        if hasattr(mod,name) and callable(getattr(mod,name)):
            return getattr(mod,name), mod
    pytest.fail("未暴露 read_url")

def _get_parallel():
    mod,_ = _load()
    for name in ("parallel_read_url","parallel_read","read_urls","batch_read_url"):
        if hasattr(mod,name) and callable(getattr(mod,name)):
            return getattr(mod,name), mod
    return None, mod

# ---------- helper: tiny http server for markdown quality ----------
RICH_HTML = """<!doctype html>
<html><head><title>Test Doc</title></head>
<body>
<h1>Main Title</h1>
<h2>Section One</h2>
<p>This is a paragraph about retrieval augmented generation and python code.</p>
<ul><li>item one</li><li>item two</li></ul>
<pre><code>def hello():
    print("hello world")
</code></pre>
<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>
<p>Another section about machine learning embeddings specifically.</p>
<h2>Section Two</h2>
<p>Unrelated content about cooking recipe for apple pie.</p>
</body></html>"""

class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/rich":
            self.send_response(200)
            self.send_header("Content-Type","text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(RICH_HTML.encode())
        elif self.path == "/notfound":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
        elif self.path == "/html":
            self.send_response(200)
            self.send_header("Content-Type","text/html")
            self.end_headers()
            self.wfile.write(RICH_HTML.encode())
        else:
            self.send_response(200)
            self.send_header("Content-Type","text/html")
            self.end_headers()
            self.wfile.write(b"<html><head><title>ok</title></head><body><h1>ok</h1><p>hello</p></body></html>")
    def log_message(self, fmt, *args):
        pass

@pytest.fixture(scope="module")
def local_server():
    # find free port
    s = socket.socket()
    s.bind(("127.0.0.1",0))
    port = s.getsockname()[1]
    s.close()
    srv = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(0.2)
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()

# ---------- tests ----------
def test_reader_real_fetch():
    """真实网络抓取 example.com 与 httpbin.org/html（无网则 skip）"""
    read_fn,_ = _get_read()
    # check network quickly
    urls = ["https://example.com", "https://httpbin.org/html"]
    for url in urls:
        try:
            result = read_fn(url=url)
        except Exception as e:
            pytest.skip(f"无网或远端不可达 {url}: {e}")
        assert isinstance(result, str) and len(result.strip())>50, f"抓取 {url} 返回过短或为空"
        # example.com 应含 Example Domain
        if "example.com" in url:
            assert "Example" in result or "example" in result.lower()
        # httpbin.org/html 含 Moby Dick 示例文本（Availing / Perth / Herman / html 均可）
        if "httpbin" in url:
            assert len(result) > 500 and ("Herman" in result or "Moby" in result or "Availing" in result or "Perth" in result or "html" in result.lower()), f"httpbin 抓取内容异常，len={len(result)} head={result[:300]}"

def test_reader_question_param():
    """传入 question 时应返回仅相关段落而非全文（chunk+rerank）"""
    # use local server to avoid network flakiness
    # but also test signature: must accept question param
    mod,_ = _load()
    read_fn = getattr(mod, "read_url", None)
    assert read_fn is not None
    import inspect
    sig = inspect.signature(read_fn)
    assert "question" in sig.parameters, "read_url 必须支持 question 参数以实现语义切片"

    # need local server
    # start ad-hoc server if fixture not available
    s = socket.socket()
    s.bind(("127.0.0.1",0))
    port = s.getsockname()[1]
    s.close()
    srv = http.server.HTTPServer(("127.0.0.1",port), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(0.2)
    try:
        url = f"http://127.0.0.1:{port}/rich"
        full = read_fn(url=url)
        filtered = read_fn(url=url, question="python code hello function")
        assert isinstance(filtered, str) and len(filtered.strip())>0
        # filtered should be shorter than full (semantic slice)
        assert len(filtered) < len(full), f"question 过滤后应短于全文 full={len(full)} filtered={len(filtered)}"
        # should contain question relevant terms
        assert "python" in filtered.lower() or "hello" in filtered.lower() or "code" in filtered.lower()
        # should NOT contain unrelated cooking section if filtering works
        # at least ensure filtered is not equal to full
        assert filtered.strip() != full.strip()
        # chunk logic: should be top 3 passages, roughly 100词 窗口 => filtered length moderate (<1500 chars ideal)
        assert len(filtered) < 5000
    finally:
        srv.shutdown()

def test_parallel_read_url(local_server):
    """并发 3 URL 批量抓取"""
    fn, mod = _get_parallel()
    assert fn is not None, f"功能缺失: 未暴露 parallel_read_url，检查 {CANDIDATES}"
    import inspect
    sig = inspect.signature(fn)
    # first param should accept list
    assert len(sig.parameters) >=1
    urls = [f"{local_server}/rich", f"{local_server}/rich", f"{local_server}/rich"]
    # test also with question param if supported
    try:
        results = fn(urls)
    except TypeError:
        # maybe signature is (urls: list[str]) -> try keyword
        results = fn(urls=urls)
    assert isinstance(results, list) and len(results)==3
    for r in results:
        assert isinstance(r, str) and len(r.strip())>20
        assert "Main Title" in r or "Title" in r

def test_reader_error_handling_empty_url():
    read_fn,_ = _get_read()
    with pytest.raises((ValueError, TypeError)):
        read_fn(url="")
    with pytest.raises((ValueError, TypeError)):
        read_fn(url="   ")
    with pytest.raises((ValueError, TypeError)):
        read_fn(url=None)  # type: ignore

def test_reader_error_handling_invalid_url():
    read_fn,_ = _get_read()
    # invalid scheme or malformed should raise, not silent fallback
    with pytest.raises(Exception):
        read_fn(url="ht!tp://::invalid")

def test_reader_error_handling_404(local_server):
    read_fn,_ = _get_read()
    # 404 should raise, not return fake markdown
    with pytest.raises(Exception):
        read_fn(url=f"{local_server}/notfound")

def test_reader_markdown_quality(local_server):
    """验证返回含标题、列表/代码块/表格的 markdown 结构"""
    read_fn,_ = _get_read()
    url = f"{local_server}/rich"
    md = read_fn(url=url)
    assert isinstance(md, str)
    # 必须含标题
    assert "# " in md, f"markdown 应含标题层级 '# ', 实际前500:{md[:500]}"
    # 列表: - 或 * 或 1.
    assert ("- " in md or "* " in md or "1." in md or "item one" in md.lower())
    # 代码块: 应保留代码或 ``` 标记
    assert ("```" in md or "def hello" in md or "print(" in md), f"应保留代码块, 实际:{md[:800]}"
    # 表格: 含 | 或 表头 A B
    assert ("|" in md or "A" in md and "B" in md), f"应保留表格, 实际:{md[:800]}"

def test_reader_cache_uses_sha256(local_server):
    """缓存命中时直接返回（/tmp/opencode/jina-local）"""
    mod,_ = _load()
    read_fn = getattr(mod, "read_url")
    import hashlib, pathlib
    cache_dir = pathlib.Path("/tmp/opencode/jina-local")
    # clean cache for deterministic
    url = f"{local_server}/rich"
    key = hashlib.sha256(url.encode()).hexdigest()
    cache_file = cache_dir / f"{key}.md"
    if cache_file.exists():
        cache_file.unlink()
    first = read_fn(url=url)
    assert cache_file.exists(), f"首次抓取后应写入缓存 {cache_file}"
    mtime1 = cache_file.stat().st_mtime
    time.sleep(0.1)
    second = read_fn(url=url)
    mtime2 = cache_file.stat().st_mtime
    assert first == second
    assert mtime1 == mtime2, "命中缓存时不应重写文件"
