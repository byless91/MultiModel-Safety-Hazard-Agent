import json
import re
from pathlib import Path

import numpy as np

from app.core.config import get_settings
from app.services.embedding_cache import (
    CACHE_VERSION,
    corpus_signature,
    embedding_cache_file,
    index_file,
    index_meta_file,
    load_embedding_cache,
    load_index_meta,
    save_embedding_cache,
    save_index_meta,
    text_hash,
)
from app.services.providers import get_provider, hash_embed

DEMO_SOURCE_MARKERS = ("演示",)
DEMO_VERSION_MARKERS = ("demo",)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD_RE = re.compile(r"[a-zA-Z0-9_]{2,}")


def _tokens(text: str) -> set[str]:
    chars = [ch for ch in text if _CJK_RE.match(ch)]
    tokens = {
        "".join(chars[index : index + 2])
        for index in range(len(chars) - 1)
        if chars[index + 1]
    }
    tokens.update(_WORD_RE.findall(text.lower()))
    return tokens


def _lexical_overlap(query: str, text: str) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    text_tokens = _tokens(text)
    return len(query_tokens & text_tokens) / len(query_tokens)


def _metadata_boost(item: dict, query: str) -> float:
    boost = 0.0
    if item.get("article"):
        boost += 1.0
    for tag in item.get("tags") or []:
        if str(tag) and str(tag) in query:
            boost += 1.0
            break
    return boost


def rerank_results(query: str, results: list[dict], top_n: int) -> list[dict]:
    """Deterministic lexical+metadata rerank over the vector candidates."""
    scored: list[dict] = []
    for item in results:
        vector = float(item.get("score") or 0.0)
        lexical = _lexical_overlap(query, str(item.get("text") or ""))
        metadata = _metadata_boost(item, query)
        clone = dict(item)
        clone["vector_score"] = round(vector, 4)
        clone["rerank_score"] = round(
            0.4 * vector + 0.4 * lexical + 0.2 * min(1.0, metadata),
            4,
        )
        scored.append(clone)
    scored.sort(key=lambda item: item["rerank_score"], reverse=True)
    return scored[:top_n]


try:
    import faiss

    HAS_FAISS = True
except Exception:  # faiss is optional; numpy fallback covers small demo corpora
    HAS_FAISS = False


def is_demo_chunk(item: dict) -> bool:
    """Return True for demo rows that must never be treated as legal evidence."""
    if not isinstance(item, dict):
        return False
    if bool(item.get("is_demo")):
        return True
    version = str(item.get("version") or "").strip().lower()
    if version in DEMO_VERSION_MARKERS:
        return True
    source = str(item.get("source") or "")
    if any(marker in source for marker in DEMO_SOURCE_MARKERS):
        return True
    return str(item.get("id") or "").lower().startswith("demo-")


def is_regulatory_evidence(item: dict) -> bool:
    """Only rows carrying article/document provenance count as legal evidence."""
    if is_demo_chunk(item):
        return False
    return bool(item.get("article") or item.get("document"))


class RAGService:
    def __init__(self, settings, provider) -> None:
        self.settings = settings
        self.provider = provider
        self.texts: list[str] = []
        self.metas: list[dict] = []
        self.hashes: list[str] = []
        self.vectors = np.zeros((0, 0), dtype=np.float32)
        self._index = None
        self.embedding_dim = 0
        self.embedding_fallback = False
        self.reranker_enabled = settings.reranker_enabled
        self.model_key = self._model_key()
        self.load()

    @property
    def cache_dir(self) -> Path:
        return Path(self.settings.faiss_index_dir)

    def _model_key(self) -> str:
        provider = getattr(self.provider, "name", "") or "unknown"
        model = getattr(self.provider, "embedding_model", "") or "default"
        return f"{provider}:{model}"

    def load(self) -> None:
        chunks = []
        knowledge_dir = self.settings.knowledge_dir
        paths = sorted(knowledge_dir.glob("*.jsonl")) + sorted(
            knowledge_dir.glob("chunks/*.jsonl")
        )
        for path in paths:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    chunks.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        self.texts = [str(item.get("text", "")) for item in chunks if item.get("text")]
        self.metas = [
            {
                "id": item.get("id"),
                "source": item.get("source", "未标注来源"),
                "version": item.get("version") or "",
                "tags": item.get("tags", []) or [],
                "collected_at": item.get("collected_at") or "",
                "article": item.get("article") or "",
                "document": item.get("document") or "",
                "risk_type": item.get("risk_type") or "",
                "scene": item.get("scene") or "",
                "effective_date": item.get("effective_date") or "",
                "is_demo": is_demo_chunk(item),
            }
            for item in chunks
        ]
        self.hashes = [text_hash(text) for text in self.texts]
        self.model_key = self._model_key()
        self.load_or_build_index()

    def load_or_build_index(self) -> None:
        """Reuse the persisted FAISS index when the corpus is unchanged.

        This is the fast path: no embedding API calls and no vector assembly.
        """
        if not self.texts:
            self.vectors = np.zeros((0, 0), dtype=np.float32)
            self._index = None
            self.embedding_dim = 0
            return
        signature = corpus_signature(self.hashes, self.model_key)
        if self._restore_persisted_index(signature):
            return
        self.rebuild()
        self._persist_index(signature)

    def _restore_persisted_index(self, signature: str) -> bool:
        if not HAS_FAISS:
            return False
        meta = load_index_meta(index_meta_file(self.cache_dir))
        if not meta or meta.get("signature") != signature:
            return False
        path = index_file(self.cache_dir)
        if not path.exists():
            return False
        try:
            self._index = faiss.read_index(str(path))
        except Exception:
            self._index = None
            return False
        self.embedding_dim = int(meta.get("dim") or 0) or int(self._index.d)
        self.embedding_fallback = bool(meta.get("embedding_fallback", False))
        self.vectors = np.zeros((0, 0), dtype=np.float32)
        return True

    def _persist_index(self, signature: str) -> None:
        if not HAS_FAISS or self._index is None:
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            faiss.write_index(self._index, str(index_file(self.cache_dir)))
            save_index_meta(
                index_meta_file(self.cache_dir),
                {
                    "version": CACHE_VERSION,
                    "signature": signature,
                    "model_key": self.model_key,
                    "count": len(self.texts),
                    "dim": int(self.embedding_dim),
                    "embedding_fallback": bool(self.embedding_fallback),
                },
            )
        except OSError:
            pass

    def rebuild(self) -> None:
        if len(self.hashes) != len(self.texts):
            self.hashes = [text_hash(text) for text in self.texts]
        if not self.texts:
            self.vectors = np.zeros((0, 0), dtype=np.float32)
            self._index = None
            self.embedding_dim = 0
            return
        vectors = self._embed_texts()
        self.vectors = np.asarray(vectors, dtype=np.float32)
        self.embedding_dim = (
            int(self.vectors.shape[1]) if self.vectors.ndim == 2 else 0
        )
        self._index = None
        if HAS_FAISS and self.vectors.shape[0] > 0:
            index = faiss.IndexFlatIP(self.vectors.shape[1])
            index.add(self.vectors)
            self._index = index

    def _embed_texts(self) -> list:
        if self.embedding_fallback:
            return hash_embed(self.texts)
        try:
            return self._embed_with_cache()
        except Exception:
            self.embedding_fallback = True
            return hash_embed(self.texts)

    def _embed_with_cache(self) -> list:
        """Embed only chunks whose text hash is absent from the cache."""
        cache_path = embedding_cache_file(self.cache_dir, self.model_key)
        cache = load_embedding_cache(cache_path, self.model_key)
        missing = [
            (index, text)
            for index, (item_hash, text) in enumerate(zip(self.hashes, self.texts))
            if item_hash not in cache
        ]
        if missing:
            fresh = self.provider.embed([text for _, text in missing])
            for (index, _), vector in zip(missing, fresh):
                cache[self.hashes[index]] = np.asarray(vector, dtype=np.float32)
            save_embedding_cache(cache_path, self.model_key, cache)
        self.embedding_fallback = False
        return [cache[item_hash] for item_hash in self.hashes]

    def search(
        self,
        query: str,
        top_k: int = 5,
        tags: list[str] | None = None,
        *,
        include_demo: bool = False,
        reranker_enabled: bool | None = None,
    ) -> list[dict]:
        if not self.texts:
            return []
        use_reranker = (
            self.settings.reranker_enabled
            if reranker_enabled is None
            else reranker_enabled
        )
        candidate_limit = top_k * 2 if use_reranker else top_k
        # Tag filtering happens after retrieval, so a tag must not be crowded
        # out of the candidate window by untagged chunks.
        candidate_window = min(
            max(top_k * 4, 200 if tags else 0),
            len(self.texts),
        )
        try:
            if self.embedding_fallback:
                raise RuntimeError("fallback embedding mode")
            query_vector = np.asarray(self.provider.embed([query]), dtype=np.float32)
        except Exception:
            if self.embedding_dim != 256:
                self.embedding_fallback = True
                self.rebuild()
            query_vector = np.asarray(hash_embed([query]), dtype=np.float32)

        if self._index is not None:
            scores, indexes = self._index.search(query_vector, candidate_window)
            pairs = [(int(i), float(s)) for i, s in zip(indexes[0], scores[0]) if i >= 0]
        else:
            dots = self.vectors @ query_vector[0]
            order = np.argsort(dots)[::-1]
            pairs = [(int(i), float(dots[i])) for i in order[:candidate_window]]

        results: list[dict] = []
        seen: set[str] = set()
        for index, score in pairs:
            if not include_demo and self.metas[index].get("is_demo"):
                continue
            meta = self.metas[index]
            if tags and not (set(tags) & set(meta.get("tags", []))):
                continue
            item_id = str(meta.get("id") or index)
            if item_id in seen:
                continue
            seen.add(item_id)
            results.append(
                {
                    **meta,
                    "id": item_id,
                    "text": self.texts[index],
                    "score": round(float(score), 4),
                }
            )
            if len(results) >= candidate_limit:
                break
        if use_reranker and results:
            results = rerank_results(query, results, top_k)
        return results


_rag: RAGService | None = None


def get_rag() -> RAGService:
    global _rag
    if _rag is None:
        _rag = RAGService(get_settings(), get_provider())
    return _rag


def reset_rag() -> None:
    global _rag
    _rag = None


def build_evidence_context(evidence: list[dict], max_items: int = 3) -> str:
    """Compact traceable evidence block used inside model prompts."""
    lines = []
    for item in evidence[:max_items]:
        label = str(item.get("source") or "未标注来源")
        article = str(item.get("article") or "")
        if article:
            label = f"{label} {article}"
        lines.append(f"- [{label}] {str(item.get('text') or '')[:200]}")
    return "\n".join(lines)


def retrieval_as_evidence(retrieval: list[dict]) -> list[dict]:
    """Convert raw RAG retrieval rows into the evidence shape used downstream."""
    return [
        {
            "id": item.get("id") or "",
            "source": item.get("source", "未标注来源"),
            "text": item.get("text", ""),
            "version": item.get("version", ""),
            "tags": item.get("tags", []),
            "score": item.get("score", 0),
            "article": item.get("article", ""),
            "document": item.get("document", ""),
            "effective_date": item.get("effective_date", ""),
            "risk_type": item.get("risk_type", ""),
            "scene": item.get("scene", ""),
            "is_demo": bool(item.get("is_demo") or is_demo_chunk(item)),
        }
        for item in retrieval
    ]
