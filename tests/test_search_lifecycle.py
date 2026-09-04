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
    (tmp_path / "search-fetcher").mkdir()
    (tmp_path / "search-core").mkdir()
    (tmp_path / "search-fetcher" / "Dockerfile").write_text("FROM golang:1.27-bookworm\n")
    (tmp_path / "search-core" / "Dockerfile").write_text("FROM rust:1.85-bookworm\n")
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

    compose_up = [command for command, _ in commands if command[:2] == ["docker", "compose"] and "up" in command]
    assert len(compose_up) == 1
    assert compose_up[0][-5:] == ["up", "-d", "search", "search-fetcher", "search-core"]
    assert len(spawned) == 1
    assert lifecycle.read_state()["last_activity"] == 100.0


def test_readiness_uses_fetcher_upstream_probe(monkeypatch, tmp_path):
    module = _load()
    probes = []
    lifecycle = module.SearchLifecycle(root=tmp_path, state_dir=tmp_path, probe=lambda url: probes.append(url) or True)

    assert lifecycle._ready() is True
    assert probes[0].endswith("/readyz")
    assert probes[1].endswith("/healthz")


def test_watchdog_stops_only_after_idle_interval(tmp_path):
    module = _load()
    lifecycle = module.SearchLifecycle(root=tmp_path, state_dir=tmp_path, idle_seconds=600, clock=lambda: 700.0)
    lifecycle.write_state({"last_activity": 101.0})
    assert lifecycle.should_stop() is False
    lifecycle.write_state({"last_activity": 100.0})
    assert lifecycle.should_stop() is True
    assert lifecycle.compose_command("stop")[-6:] == ["stop", "--timeout", "1", "search", "search-fetcher", "search-core"]


def test_lease_pulls_missing_dockerfile_base_images_before_start(tmp_path):
    module = _load()
    (tmp_path / "search-fetcher").mkdir()
    (tmp_path / "search-core").mkdir()
    (tmp_path / "search-fetcher" / "Dockerfile").write_text("FROM golang:1.27-bookworm AS build\nFROM gcr.io/distroless/static-debian12\n")
    (tmp_path / "search-core" / "Dockerfile").write_text("FROM rust:1.85-bookworm AS build\nFROM debian:bookworm-slim\n")
    commands = []

    class Result:
        def __init__(self, returncode=0):
            self.returncode = returncode
            self.stdout = ""
            self.stderr = ""

    def runner(command, **kwargs):
        commands.append(command)
        return Result(1 if command[:3] == ["docker", "image", "inspect"] else 0)

    lifecycle = module.SearchLifecycle(
        root=tmp_path,
        state_dir=tmp_path,
        runner=runner,
        probe=lambda url: True,
        spawner=lambda *args, **kwargs: None,
    )

    with lifecycle.lease():
        pass

    assert [command[2] for command in commands if command[:2] == ["docker", "pull"]] == [
        "golang:1.27-bookworm",
        "gcr.io/distroless/static-debian12",
        "rust:1.85-bookworm",
        "debian:bookworm-slim",
    ]
    assert commands[-1][-5:] == ["up", "-d", "search", "search-fetcher", "search-core"]


def test_missing_docker_cli_is_a_lifecycle_error(tmp_path):
    module = _load()
    (tmp_path / "search-fetcher").mkdir()
    (tmp_path / "search-core").mkdir()
    (tmp_path / "search-fetcher" / "Dockerfile").write_text("FROM golang:1.27-bookworm\n")
    (tmp_path / "search-core" / "Dockerfile").write_text("FROM rust:1.85-bookworm\n")
    lifecycle = module.SearchLifecycle(
        root=tmp_path,
        state_dir=tmp_path,
        runner=lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("docker")),
        probe=lambda url: False,
    )

    with pytest.raises(module.SearchLifecycleError, match="docker command unavailable"):
        with lifecycle.lease():
            pass


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
