"""Utility 工具补齐测试 - 替代 jina utility/rerank剩余工具

要求至少8测试：
- test_deduplicate_strings
- test_deduplicate_images
- test_classify_text
- test_expand_query
- test_extract_pdf
- test_guess_datetime_url
- test_primer
- test_utils_error_handling

TDD GREEN: 对应 mcp-gateway/src/utils.py 已实现
"""
import importlib.util
import pathlib
import sys
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATES = [
    ROOT / "mcp-gateway" / "src" / "utils.py",
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
    assert path is not None, f"功能缺失: utils 模块不存在 {CANDIDATES}"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod, path


def _get_fn(name):
    mod, _ = _load()
    if hasattr(mod, name) and callable(getattr(mod, name)):
        return getattr(mod, name), mod
    pytest.fail(f"功能缺失: 未暴露 {name} 入口")


def test_deduplicate_strings():
    """输入5字符串含重复语义，返回 top_k 去重后数量 < 原，相似度高的被合并"""
    fn, _ = _get_fn("deduplicate_strings")
    strings = [
        "hello world",
        "hello world",
        "hello world!",
        "goodbye world",
        "foo bar",
    ]
    result = fn(strings, top_k=3)
    assert isinstance(result, list), "deduplicate_strings 应返回 list"
    assert len(result) < len(strings), f"去重后数量应 < 原，实际 {len(result)} vs {len(strings)}"
    assert len(result) <= 3, f"top_k=3 约束，实际 {len(result)}"
    # 相似度高的应被合并，保留语义独特项：至少应保留 goodbye world 与 foo bar
    combined = " ".join(result).lower()
    assert "goodbye" in combined or "foo" in combined, f"语义独特项未保留，实际 {result}"
    # 不应含重复 hello world 多次
    hello_count = sum(1 for s in result if "hello world" in s.lower())
    assert hello_count <= 1, f"相似句未合并，实际 {result}"
    # top_k 不传时，也应去重且 <5
    result2 = fn(strings)
    assert isinstance(result2, list)
    assert len(result2) < len(strings)


def test_deduplicate_images():
    """用文本路径模拟，返回 top_k"""
    fn, _ = _get_fn("deduplicate_images")
    images = [
        "images/cat.jpg",
        "images/cat.jpg",
        "images/cat_copy.jpg",
        "images/dog.jpg",
        "images/bird.jpg",
    ]
    result = fn(images, top_k=3)
    assert isinstance(result, list), "deduplicate_images 应返回 list"
    assert len(result) <= 3
    assert len(result) < len(images) or len(result) == 3, f"去重失败，实际 {result}"
    # 所有返回应为原列表子集
    for r in result:
        assert r in images, f"返回项不在原列表，实际 {r}"
    # 无 top_k 情况
    result2 = fn(images)
    assert isinstance(result2, list)
    assert len(result2) >= 1

    # alternative alias k
    result3 = fn(images, k=2)
    assert len(result3) <= 2


def test_classify_text():
    """输入 texts + labels，返回分类"""
    fn, _ = _get_fn("classify_text")
    texts = [
        "I love playing football",
        "Stock market is crashing",
        "Python programming tutorial",
    ]
    labels = ["sports", "finance", "technology"]
    results = fn(texts, labels)
    assert isinstance(results, list), "classify_text 应返回 list"
    assert len(results) == len(texts), f"返回数量应等于 texts 长度 {len(texts)}，实际 {len(results)}"
    for item in results:
        assert isinstance(item, dict), "分类结果项应为 dict"
        # label 字段兼容
        label = item.get("label") or item.get("predicted_label") or item.get("prediction")
        assert label is not None, f"缺 label 字段，实际 {list(item.keys())}"
        assert label in labels, f"label {label} 不在输入 labels {labels}"
        # score 兼容
        score = item.get("score")
        if score is None:
            score = item.get("confidence") or item.get("relevance_score")
        assert score is not None, f"缺分数，实际 {list(item.keys())}"
        assert isinstance(score, (int, float))
        assert 0 <= float(score) <= 1.0 + 1e-6, f"分数应在0-1，实际 {score}"

    # also test single text classification via same interface? ensure works
    single = fn(["I love football"], ["sports", "finance"])
    assert len(single) == 1
    assert (single[0].get("label") or single[0].get("predicted_label")) in ["sports", "finance"]


def test_expand_query():
    """输入 query 返回 3 扩展 query 含原词"""
    fn, _ = _get_fn("expand_query")
    query = "machine learning"
    results = fn(query)
    assert isinstance(results, list), "expand_query 应返回 list"
    assert len(results) == 3, f"默认应返回3扩展，实际 {len(results)}"
    for q in results:
        assert isinstance(q, str), "扩展项应为 str"
        assert q.strip(), "扩展项不能为空"
        assert query.lower() in q.lower() or query in q, f"扩展应含原词 {query!r}，实际 {q!r}"

    # 指定 num
    results2 = fn(query, num=5)
    assert len(results2) == 5
    for q in results2:
        assert query.lower() in q.lower()

    # 原词本身应存在于返回中至少一条精确或包含
    assert any(query.lower() == r.lower() or query.lower() in r.lower() for r in results)


def test_extract_pdf():
    """给定 PDF URL，返回含 figures/tables 结构"""
    fn, _ = _get_fn("extract_pdf")
    # 使用稳定公共 PDF URL；若网络不可用，stub 也应通过
    pdf_url = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
    result = fn(pdf_url)
    assert isinstance(result, dict), "extract_pdf 应返回 dict"
    assert "figures" in result, f"缺 figures，实际 {list(result.keys())}"
    assert "tables" in result, f"缺 tables，实际 {list(result.keys())}"
    # text 字段兼容 text/content/extracted
    text_field = result.get("text")
    if text_field is None:
        text_field = result.get("content") or result.get("extracted")
    assert text_field is not None, f"缺 text，实际 {list(result.keys())}"
    assert isinstance(text_field, str), "text 应为 str"
    assert len(text_field) > 0, "text 不能为空"
    assert isinstance(result["figures"], list)
    assert isinstance(result["tables"], list)

    # also test alias pdf_url kwarg
    result2 = fn(url=pdf_url) if "url" in fn.__code__.co_varnames else fn(pdf_url)
    # at least structure check via try alternative calling
    try:
        alt = fn(pdf_url=pdf_url)  # type: ignore
        assert isinstance(alt, dict)
        assert "figures" in alt
    except TypeError:
        pass


def test_guess_datetime_url():
    """给定 URL 返回时间戳与置信度"""
    fn, _ = _get_fn("guess_datetime_url")
    url = "https://example.com"
    result = fn(url)
    assert isinstance(result, dict), "guess_datetime_url 应返回 dict"
    assert "datetime" in result, f"缺 datetime，实际 {list(result.keys())}"
    assert "confidence" in result, f"缺 confidence，实际 {list(result.keys())}"
    dt_val = result["datetime"]
    conf = result["confidence"]
    assert isinstance(dt_val, str) and dt_val.strip(), "datetime 应为非空字符串"
    assert isinstance(conf, (int, float)), "confidence 应为数字"
    assert 0 <= float(conf) <= 1.0 + 1e-6, f"confidence 应在0-1，实际 {conf}"
    # datetime 应可 parse 或至少含年份
    assert any(c.isdigit() for c in dt_val), f"datetime 应含数字，实际 {dt_val}"
    assert len(dt_val) >= 8, f"datetime 长度过短，实际 {dt_val}"


def test_primer():
    """返回时间/位置上下文"""
    fn, _ = _get_fn("primer")
    result = fn()
    assert isinstance(result, dict), "primer 应返回 dict"
    # datetime/timezone/locale 至少其一，使用兼容检查
    has_dt = "datetime" in result or "utc" in result or "timestamp" in result
    assert has_dt, f"primer 缺 datetime，实际 {list(result.keys())}"
    # timezone
    tz = result.get("timezone") or result.get("timezone_offset") or result.get("tz")
    assert tz is not None, f"缺 timezone，实际 {list(result.keys())}"
    assert isinstance(tz, str) and tz.strip()
    # locale/location
    loc = result.get("locale") or result.get("location") or result.get("language")
    assert loc is not None, f"缺 locale/location，实际 {list(result.keys())}"
    # datetime 格式检查
    dt_val = result.get("datetime") or result.get("utc")
    if isinstance(dt_val, str):
        assert "T" in dt_val or "-" in dt_val, f"datetime 格式异常，实际 {dt_val}"


def test_utils_error_handling():
    """空参抛错"""
    # deduplicate_strings 空参
    dedup, _ = _get_fn("deduplicate_strings")
    with pytest.raises((ValueError, TypeError)):
        dedup([])
    with pytest.raises((ValueError, TypeError)):
        dedup(None)  # type: ignore
    with pytest.raises((ValueError, TypeError)):
        dedup([""])  # type: ignore
    with pytest.raises((ValueError, TypeError)):
        dedup(["   "])

    # deduplicate_images 空参
    dedup_img, _ = _get_fn("deduplicate_images")
    with pytest.raises((ValueError, TypeError)):
        dedup_img([])
    with pytest.raises((ValueError, TypeError)):
        dedup_img(None)  # type: ignore

    # classify 空参
    clf, _ = _get_fn("classify_text")
    with pytest.raises((ValueError, TypeError)):
        clf([], ["a"])
    with pytest.raises((ValueError, TypeError)):
        clf(["hello"], [])
    with pytest.raises((ValueError, TypeError)):
        clf(None, ["a"])  # type: ignore
    with pytest.raises((ValueError, TypeError)):
        clf(["a"], None)  # type: ignore
    with pytest.raises((ValueError, TypeError)):
        clf([""], ["a"])
    with pytest.raises((ValueError, TypeError)):
        clf(["hello"], [""])

    # expand_query 空参
    exp, _ = _get_fn("expand_query")
    with pytest.raises((ValueError, TypeError)):
        exp("")
    with pytest.raises((ValueError, TypeError)):
        exp(None)  # type: ignore
    with pytest.raises((ValueError, TypeError)):
        exp("   ")

    # extract_pdf 空参
    ext, _ = _get_fn("extract_pdf")
    with pytest.raises((ValueError, TypeError)):
        ext("")
    with pytest.raises((ValueError, TypeError)):
        ext(None)  # type: ignore
    with pytest.raises((ValueError, TypeError)):
        ext("   ")

    # guess_datetime_url 空参
    guess, _ = _get_fn("guess_datetime_url")
    with pytest.raises((ValueError, TypeError)):
        guess("")
    with pytest.raises((ValueError, TypeError)):
        guess(None)  # type: ignore
    with pytest.raises((ValueError, TypeError)):
        guess("not a url")
    with pytest.raises((ValueError, TypeError)):
        guess("ftp://example.com")

    # primer 不抛错，即使无参也应返回
    prim, _ = _get_fn("primer")
    # primer() should not raise even with no args; but primer(None) maybe ignore?
    # 确保 primer 空调用正常
    r = prim()
    assert isinstance(r, dict)
