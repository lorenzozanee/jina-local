import importlib
import sys



def test_dedup_and_classify_share_gateway_embedding_batch(monkeypatch):
    utils = importlib.import_module("utils")
    calls = []

    def fake_embeddings(texts):
        calls.append(list(texts))
        return [[float(index == position) for index in range(len(texts))] for position in range(len(texts))]

    monkeypatch.setattr(utils, "_get_embeddings", fake_embeddings)
    utils.deduplicate_strings(["one", "two"])
    utils.classify_text(["one"], ["label"])
    assert calls == [["one", "two"], ["label", "one"]]
