import importlib.util
import pathlib
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "mcp-gateway" / "src" / "search_lifecycle.py"


def _load():
    spec = importlib.util.spec_from_file_location("search_lifecycle", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["search_lifecycle"] = module
    spec.loader.exec_module(module)
    return module


def test_lease_starts_native_services_once_and_records_activity(tmp_path):
    module = _load()
    commands = []
    spawned = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    lifecycle = module.SearchLifecycle(
        root=tmp_path,
        state_dir=tmp_path,
        idle_seconds=600,
        runner=lambda command, **kwargs: commands.append((command, kwargs)) or Result(),
        probe=lambda url: True,
        spawner=lambda command, **kwargs: spawned.append((command, kwargs)),
        clock=lambda: 100.0,
    )

    with lifecycle.lease():
        pass
    with lifecycle.lease():
        pass

    assert len(commands) == 1
    assert commands[0][0][-5:] == ["up", "-d", "search", "search-fetcher", "search-core"]
    assert len(spawned) == 1
    assert lifecycle.read_state()["last_activity"] == 100.0


def test_watchdog_stops_only_after_idle_interval(tmp_path):
    module = _load()
    lifecycle = module.SearchLifecycle(root=tmp_path, state_dir=tmp_path, idle_seconds=600, clock=lambda: 700.0)
    lifecycle.write_state({"last_activity": 101.0})
    assert lifecycle.should_stop() is False
    lifecycle.write_state({"last_activity": 100.0})
    assert lifecycle.should_stop() is True


def test_search_cache_hit_does_not_acquire_lifecycle(monkeypatch, tmp_path):
    search_source = ROOT / "mcp-gateway" / "src" / "search.py"
    spec = importlib.util.spec_from_file_location("search", search_source)
    assert spec and spec.loader
    search = importlib.util.module_from_spec(spec)
    sys.modules["search"] = search
    spec.loader.exec_module(search)
    monkeypatch.setattr(search, "CACHE_DIR", tmp_path)
    search._write_cache("cached", [{
        "title": "cached title",
        "url": "https://example.com/cached",
        "content": "cached content",
        "source": "searxng",
        "retrieved_at": "2026-09-04T00:00:00Z",
    }])
    monkeypatch.setattr(search, "_native_lifecycle", lambda: pytest.fail("cache hit must not start services"))

    assert search.search_web("cached")


def test_native_fetch_releases_lifecycle_after_request(monkeypatch):
    search_source = ROOT / "mcp-gateway" / "src" / "search.py"
    spec = importlib.util.spec_from_file_location("search", search_source)
    assert spec and spec.loader
    search = importlib.util.module_from_spec(spec)
    sys.modules["search"] = search
    spec.loader.exec_module(search)
    calls = []

    class Lease:
        def __enter__(self):
            calls.append("enter")

        def __exit__(self, exc_type, exc, traceback):
            calls.append("exit")

    class Lifecycle:
        def lease(self):
            return Lease()

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": []} if "fetcher" in self.url else {"results": []}

    def post(url, **kwargs):
        response = Response()
        response.url = url
        return response

    monkeypatch.setattr(search, "_native_lifecycle", lambda: Lifecycle())
    monkeypatch.setattr(search.requests, "post", post)
    assert search._fetch_candidates("query", 1) == []
    assert calls == ["enter", "exit"]
