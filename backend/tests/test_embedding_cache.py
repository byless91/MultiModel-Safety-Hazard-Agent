"""Embedding cache and persisted-index reuse for the RAG service."""

import json

import numpy as np

from app.core.config import Settings
from app.services.embedding_cache import (
    corpus_signature,
    embedding_cache_file,
    load_embedding_cache,
    save_embedding_cache,
    text_hash,
)
from app.services.providers import MockProvider, hash_embed
from app.services.rag import RAGService


class _CountingProvider(MockProvider):
    """Mock provider that records every embed() call."""

    name = "counting"
    embedding_model = "counting-embed"

    def __init__(self) -> None:
        self.embed_calls: list[list[str]] = []

    def embed(self, texts):
        self.embed_calls.append(list(texts))
        return hash_embed(list(texts))

    @property
    def embedded_texts(self) -> list[str]:
        return [text for batch in self.embed_calls for text in batch]


def _write_chunks(directory, texts):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "chunks.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "id": f"chunk-{index}",
                    "document": "测试法规",
                    "article": "第二十八条",
                    "source": "测试",
                    "version": "v1",
                    "tags": ["消防"],
                    "text": text,
                },
                ensure_ascii=False,
            )
            for index, text in enumerate(texts)
        ),
        encoding="utf-8",
    )
    return path


def _settings(tmp_path, knowledge_dir):
    return Settings(
        provider_mode="mock",
        knowledge_dir=str(knowledge_dir),
        faiss_index_dir=str(tmp_path / "faiss"),
        _env_file=None,
    )


def test_text_hash_is_stable_and_content_addressed():
    assert text_hash("疏散通道") == text_hash("疏散通道")
    assert text_hash("疏散通道") != text_hash("安全出口")


def test_corpus_signature_changes_with_content_and_model():
    hashes = [text_hash("a"), text_hash("b")]
    base = corpus_signature(hashes, "mock:model-a")
    assert base == corpus_signature(hashes, "mock:model-a")
    assert base != corpus_signature(hashes, "mock:model-b")
    assert base != corpus_signature(hashes + [text_hash("c")], "mock:model-a")


def test_embedding_cache_roundtrip(tmp_path):
    path = embedding_cache_file(tmp_path, "mock:model-a")
    vectors = {
        text_hash("第一条"): np.array([0.1, 0.2, 0.3], dtype=np.float32),
        text_hash("第二条"): np.array([0.4, 0.5, 0.6], dtype=np.float32),
    }
    save_embedding_cache(path, "mock:model-a", vectors)
    loaded = load_embedding_cache(path, "mock:model-a")
    assert set(loaded) == set(vectors)
    assert np.allclose(loaded[text_hash("第一条")], vectors[text_hash("第一条")])


def test_embedding_cache_ignores_foreign_model(tmp_path):
    path = embedding_cache_file(tmp_path, "mock:model-a")
    save_embedding_cache(
        path, "mock:model-a", {text_hash("第一条"): np.array([1.0, 2.0])}
    )
    assert load_embedding_cache(path, "mock:model-b") == {}


def test_embedding_cache_survives_corrupt_file(tmp_path):
    path = embedding_cache_file(tmp_path, "mock:model-a")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not an npz file")
    assert load_embedding_cache(path, "mock:model-a") == {}


def test_missing_cache_file_returns_empty(tmp_path):
    assert load_embedding_cache(tmp_path / "nope.npz", "mock:model-a") == {}


def test_second_load_reuses_cache_without_embedding(tmp_path):
    knowledge = tmp_path / "knowledge"
    _write_chunks(knowledge, ["不得占用疏散通道。", "禁止堵塞安全出口。"])
    settings = _settings(tmp_path, knowledge)

    first = _CountingProvider()
    rag_one = RAGService(settings, first)
    assert len(first.embedded_texts) == 2
    assert not rag_one.embedding_fallback

    second = _CountingProvider()
    rag_two = RAGService(settings, second)
    assert second.embed_calls == []
    assert rag_two.embedding_fallback is False


def test_adding_one_chunk_only_embeds_the_new_text(tmp_path):
    knowledge = tmp_path / "knowledge"
    _write_chunks(knowledge, ["不得占用疏散通道。", "禁止堵塞安全出口。"])
    settings = _settings(tmp_path, knowledge)

    first = _CountingProvider()
    RAGService(settings, first)
    assert len(first.embedded_texts) == 2

    _write_chunks(
        knowledge,
        ["不得占用疏散通道。", "禁止堵塞安全出口。", "林区防火期内禁止野外用火。"],
    )
    second = _CountingProvider()
    RAGService(settings, second)
    assert second.embedded_texts == ["林区防火期内禁止野外用火。"]


def test_persisted_index_is_reused_when_corpus_unchanged(tmp_path):
    knowledge = tmp_path / "knowledge"
    _write_chunks(knowledge, ["不得占用疏散通道。", "禁止堵塞安全出口。"])
    settings = _settings(tmp_path, knowledge)

    provider_one = _CountingProvider()
    rag_one = RAGService(settings, provider_one)

    provider_two = _CountingProvider()
    rag_two = RAGService(settings, provider_two)
    assert provider_two.embed_calls == []
    if rag_two._index is not None:
        results = rag_two.search("疏散通道占用", top_k=2)
        assert results
        assert any("疏散通道" in item["text"] for item in results)


def test_changed_corpus_invalidates_persisted_index(tmp_path):
    knowledge = tmp_path / "knowledge"
    _write_chunks(knowledge, ["不得占用疏散通道。"])
    settings = _settings(tmp_path, knowledge)
    RAGService(settings, _CountingProvider())

    _write_chunks(knowledge, ["不得占用疏散通道。", "新的法规条款内容。"])
    provider = _CountingProvider()
    RAGService(settings, provider)
    assert provider.embedded_texts == ["新的法规条款内容。"]
