"""R2/T05: never search one embedding space with another space's query."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import numpy as np
import pytest
from app.core.config import get_settings
from app.services import rag as rag_module
from app.services.embedding_cache import embedding_cache_file, index_meta_file, load_embedding_cache
from app.services.providers import hash_embed
from app.services.rag import HASH_EMBEDDING_SPACE, RAGService, retrieval_as_evidence


class ControlledProvider:
    name = "controlled-provider"
    embedding_model = "controlled-v1"

    def __init__(self, dimension=2):
        self.dimension = dimension
        self.fail_queries = False
        self.fail_all = False
        self.invalid = None
        self.calls = []
        self.entered = Event()
        self.release = Event()
        self.block_new = False

    def embed(self, texts):
        self.calls.append(list(texts))
        if self.fail_all or (self.fail_queries and texts == ["query-first"]):
            raise TimeoutError("offline embedding failure")
        if self.block_new and "new-corpus" in texts:
            self.entered.set()
            if not self.release.wait(3):
                raise TimeoutError("test synchronization timed out")
        if self.invalid == "short":
            return []
        if self.invalid == "nan":
            return [[float("nan")] * self.dimension for _ in texts]
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimension
            vector[1 if text == "corpus-second" else 0] = 1.0
            vectors.append(vector)
        return vectors


def write_corpus(directory, *, extra=False):
    directory.mkdir(exist_ok=True)
    texts = ["corpus-first", "corpus-second"] + (["new-corpus"] if extra else [])
    (directory / "corpus.jsonl").write_text("\n".join(json.dumps({
        "id": f"chunk-{index}", "text": text, "source": "test", "document": "test regulation",
        "article": "第一条", "version": "test", "tags": [],
    }) for index, text in enumerate(texts)), encoding="utf-8")


@pytest.fixture(params=[False, True], ids=["numpy", "faiss"])
def factory(request, tmp_path, monkeypatch):
    use_faiss = request.param
    if use_faiss and not rag_module.HAS_FAISS:
        pytest.skip("Optional FAISS is not installed")
    monkeypatch.setattr(rag_module, "HAS_FAISS", use_faiss)
    knowledge = tmp_path / "knowledge"
    write_corpus(knowledge)
    settings = get_settings().model_copy(update={
        "knowledge_dir": knowledge, "faiss_index_dir": tmp_path / "index",
        "reranker_enabled": False, "embedding_recovery_seconds": 30.0,
    })

    def create(provider=None):
        provider = provider or ControlledProvider()
        return RAGService(settings, provider), provider
    return create, settings, use_faiss


@pytest.mark.parametrize("dimension", [2, 256])
def test_query_failure_switches_corpus_and_query_even_when_dimensions_match(factory, dimension, caplog):
    create, settings, _ = factory
    rag, provider = create(ControlledProvider(dimension))
    real_cache = embedding_cache_file(settings.faiss_index_dir, rag.model_key)
    original = real_cache.read_bytes()
    provider.fail_queries = True
    results = rag.search("query-first", top_k=2)
    assert results
    assert rag.embedding_fallback is True
    assert rag.embedding_space == HASH_EMBEDDING_SPACE
    assert rag.embedding_dim == 256
    expected = np.asarray(hash_embed(rag.texts)) @ np.asarray(hash_embed(["query-first"]))[0]
    by_id = {row["id"]: row for row in results}
    for index, score in enumerate(expected):
        assert by_id[f"chunk-{index}"]["score"] == pytest.approx(float(score), abs=1e-4)
    assert real_cache.read_bytes() == original
    hash_cache = load_embedding_cache(embedding_cache_file(settings.faiss_index_dir, HASH_EMBEDDING_SPACE),
                                      HASH_EMBEDDING_SPACE)
    assert len(hash_cache) == 2
    assert all(len(vector) == 256 for vector in hash_cache.values())
    assert retrieval_as_evidence(results)[0]["embedding_fallback"] is True
    assert "同时切换" in caplog.text


def test_recovery_is_cooled_down_then_validates_query_and_cached_corpus(factory, monkeypatch, caplog):
    create, _, _ = factory
    clock = [100.0]
    monkeypatch.setattr(rag_module.time, "monotonic", lambda: clock[0])
    rag, provider = create()
    provider.fail_queries = True
    rag.search("query-first")
    calls = len(provider.calls)
    clock[0] = 110.0
    rag.search("query-first")
    assert len(provider.calls) == calls
    clock[0] = 131.0
    provider.fail_queries = False
    with caplog.at_level("INFO"):
        results = rag.search("query-first")
    assert rag.embedding_fallback is False and rag.embedding_dim == 2
    assert results[0]["id"] == "chunk-0" and results[0]["score"] == 1.0
    assert provider.calls[calls:] == [["query-first"]]
    assert "恢复 provider" in caplog.text


def test_failed_recovery_preserves_hash_index(factory, monkeypatch):
    create, _, _ = factory
    clock = [100.0]
    monkeypatch.setattr(rag_module.time, "monotonic", lambda: clock[0])
    provider = ControlledProvider()
    provider.fail_all = True
    rag, _ = create(provider)
    old_vectors = rag.vectors.copy()
    clock[0] = 131.0
    assert rag.search("query-first")
    assert rag.embedding_fallback and rag.embedding_space == HASH_EMBEDDING_SPACE
    np.testing.assert_array_equal(rag.vectors, old_vectors)


@pytest.mark.parametrize("invalid", ["short", "nan"])
def test_invalid_provider_batches_cannot_poison_real_cache(factory, invalid):
    create, settings, _ = factory
    provider = ControlledProvider()
    provider.invalid = invalid
    rag, _ = create(provider)
    assert rag.embedding_fallback
    assert not embedding_cache_file(settings.faiss_index_dir, rag.model_key).exists()
    assert rag.search("query-first")
    provider.invalid = None
    rag.rebuild()
    assert not rag.embedding_fallback and rag.embedding_dim == 2
    assert rag.search("query-first")[0]["id"] == "chunk-0"


def test_restart_after_query_failure_reuses_unmodified_real_cache(factory):
    create, _, _ = factory
    rag, provider = create()
    provider.fail_queries = True
    rag.search("query-first")
    restored, fresh = create()
    assert fresh.calls == []
    assert not restored.embedding_fallback
    assert restored.search("query-first")[0]["score"] == 1.0


def test_recovery_reembeds_corpus_if_provider_dimension_changed(factory, monkeypatch):
    create, _, _ = factory
    clock = [100.0]
    monkeypatch.setattr(rag_module.time, "monotonic", lambda: clock[0])
    rag, provider = create()
    provider.dimension = 3
    assert rag.search("query-first")
    assert rag.embedding_fallback
    clock[0] = 131.0
    assert rag.search("query-first")[0]["score"] == 1.0
    assert rag.embedding_dim == 3 and not rag.embedding_fallback
    assert provider.calls[-1] == ["corpus-first", "corpus-second"]


def test_failed_load_rolls_back_corpus_and_index(factory, monkeypatch):
    create, settings, _ = factory
    rag, _ = create()
    original = (list(rag.texts), list(rag.metas), rag._index, rag.embedding_space)
    write_corpus(settings.knowledge_dir, extra=True)
    with monkeypatch.context() as change:
        def reject(vectors):
            raise RuntimeError("index construction failed")
        change.setattr(rag, "_prepare_index", reject)
        with pytest.raises(RuntimeError, match="construction failed"):
            rag.load()
    assert (rag.texts, rag.metas, rag._index, rag.embedding_space) == original
    assert rag.search("query-first")[0]["id"] == "chunk-0"


def test_queries_cannot_read_half_rebuilt_corpus(factory):
    create, settings, _ = factory
    rag, provider = create()
    write_corpus(settings.knowledge_dir, extra=True)
    provider.block_new = True
    started = Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        rebuilding = pool.submit(rag.load)
        assert provider.entered.wait(2)

        def search():
            started.set()
            return rag.search("query-first", top_k=3)
        searching = pool.submit(search)
        try:
            assert started.wait(2)
            assert not searching.done()
        finally:
            provider.release.set()
        rebuilding.result(timeout=3)
        results = searching.result(timeout=3)
    assert {row["id"] for row in results} == {"chunk-0", "chunk-1", "chunk-2"}
    assert all(row["text"] == rag.texts[int(row["id"].split('-')[1])] for row in results)


def test_persisted_index_metadata_names_the_space(factory):
    create, settings, use_faiss = factory
    rag, _ = create()
    if use_faiss:
        meta = json.loads(index_meta_file(settings.faiss_index_dir).read_text(encoding="utf-8"))
        assert meta["index_version"] == 2 and meta["embedding_space"] == rag.model_key
    assert rag.search("query-first", top_k=0) == []
