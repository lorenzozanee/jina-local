import importlib.util
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "test_search_lifecycle_runtime.py"


def _load():
    spec = importlib.util.spec_from_file_location("test_search_lifecycle_runtime", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_commands_target_only_native_search_services():
    module = _load()
    assert module.compose_command(ROOT, "build")[-3:] == ["search", "search-fetcher", "search-core"]
    assert module.compose_command(ROOT, "up")[-5:] == ["up", "-d", "search", "search-fetcher", "search-core"]
    assert module.compose_command(ROOT, "stop")[-4:] == ["stop", "search", "search-fetcher", "search-core"]


def test_runtime_cleanup_does_not_mask_the_original_failure(monkeypatch):
    module = _load()
    calls = []

    monkeypatch.setattr(module.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)))
    module.stop_services(ROOT)

    assert calls[0][1]["check"] is False
