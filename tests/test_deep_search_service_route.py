import importlib


def test_gateway_deep_search_uses_service_route(monkeypatch):
    gateway = importlib.import_module("gateway")
    calls = []

    def fake_service(query, num=5, chunk_size=100, **kwargs):
        calls.append((query, num, chunk_size, kwargs))
        return [{"title": "service", "url": "https://service"}]

    monkeypatch.setattr(gateway, "_search_deep", fake_service)
    result = gateway.search_web_deep("gpu", num=2, chunk_size=50)
    assert result == [{"title": "service", "url": "https://service"}]
    assert calls == [("gpu", 2, 50, {})]
