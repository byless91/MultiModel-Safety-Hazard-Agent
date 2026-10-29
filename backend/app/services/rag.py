import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

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

logger = logging.getLogger("safety_hazard.rag")

DEMO_SOURCE_MARKERS = ("演示",)
DEMO_VERSION_MARKERS = ("demo",)
HASH_EMBEDDING_SPACE = "hash:md5-v1:256"
INDEX_FORMAT_VERSION = 2

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
    """Deterministic lexical+metadata rerank over the vector candidates.

    权重收敛在 Settings（B5/WP3.4）：RERANK_VECTOR/LEXICAL/METADATA_WEIGHT。
    """
    from app.core.config import get_settings as _get_settings

    weights = _get_settings()
    scored: list[dict] = []
    for item in results:
        vector = float(item.get("score") or 0.0)
        lexical = _lexical_overlap(query, str(item.get("text") or ""))
        metadata = _metadata_boost(item, query)
        clone = dict(item)
        clone["vector_score"] = round(vector, 4)
        clone["rerank_score"] = round(
            weights.rerank_vector_weight * vector
            + weights.rerank_lexical_weight * lexical
            + weights.rerank_metadata_weight * min(1.0, metadata),
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
        self.embedding_space = self.model_key
        self._next_recovery_at = 0.0
        # 读写锁：重建期间查询读不到半新半旧的状态（B1 审查项竞态）
        self._lock = threading.RLock()
        self.load()

    @property
    def cache_dir(self) -> Path:
        return Path(self.settings.faiss_index_dir)

    def readiness_snapshot(self) -> dict:
        """Inspect the active index without rebuilding vectors or waiting on a model call."""
        if not self._lock.acquire(blocking=False):
            return {"chunks": 0, "index_ready": False}
        try:
            count = len(self.texts)
            chunks = sum(bool(value.strip()) and not is_demo_chunk(meta)
                         for value, meta in zip(self.texts, self.metas, strict=True))
            if self._index is not None:
                index_ready = self._index.ntotal == count and self._index.d == self.embedding_dim > 0
            else:
                index_ready = self.vectors.shape == (count, self.embedding_dim) and self.embedding_dim > 0
            return {"chunks": chunks, "index_ready": index_ready and count == len(self.metas)}
        finally:
            self._lock.release()

    def _model_key(self) -> str:
        provider = getattr(self.provider, "name", "") or "unknown"
        model = getattr(self.provider, "embedding_model", "") or "default"
        return f"{provider}:{model}"

    def load(self) -> None:
        with self._lock:
            fields = ("texts", "metas", "hashes", "model_key", "vectors", "_index", "embedding_dim",
                      "embedding_fallback", "embedding_space", "_next_recovery_at")
            previous = {name: getattr(self, name) for name in fields}
            try:
                self._load_locked()
            except Exception:
                # Failed corpus/index construction must not publish a partial state.
                for name, value in previous.items():
                    setattr(self, name, value)
                raise

    def _load_locked(self) -> None:
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
                    item = json.loads(line)
                    if isinstance(item, dict) and item.get("text"):
                        chunks.append(item)
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
            self.embedding_fallback = False
            self.embedding_space = self.model_key
            return
        signature = corpus_signature(self.hashes, self.model_key)
        if self._restore_persisted_index(signature):
            return
        self._rebuild_locked()
        self._persist_index()

    def _restore_persisted_index(self, signature: str) -> bool:
        if not HAS_FAISS:
            return False
        meta = load_index_meta(index_meta_file(self.cache_dir))
        if (not meta or meta.get("signature") != signature
                or meta.get("index_version") != INDEX_FORMAT_VERSION
                or meta.get("embedding_space") != self.model_key
                or meta.get("embedding_fallback")):
            return False
        path = index_file(self.cache_dir)
        if not path.exists():
            return False
        try:
            candidate = faiss.read_index(str(path))
            if (candidate.d <= 0 or candidate.d != meta.get("dim")
                    or candidate.ntotal != len(self.texts) or meta.get("count") != len(self.texts)):
                raise ValueError("Persisted index shape does not match corpus metadata")
        except Exception:
            logger.warning("持久化索引无效，使用 embedding 缓存重建", exc_info=True)
            return False
        self._index = candidate
        self.embedding_dim = int(candidate.d)
        self.embedding_fallback = False
        self.embedding_space = self.model_key
        self._next_recovery_at = 0.0
        self.vectors = np.zeros((0, 0), dtype=np.float32)
        return True

    def _persist_index(self) -> None:
        if not HAS_FAISS or self._index is None:
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            faiss.write_index(self._index, str(index_file(self.cache_dir)))
            save_index_meta(
                index_meta_file(self.cache_dir),
                {
                    "version": CACHE_VERSION,
                    "index_version": INDEX_FORMAT_VERSION,
                    "signature": corpus_signature(self.hashes, self.embedding_space),
                    "embedding_space": self.embedding_space,
                    "model_key": self.model_key,
                    "count": len(self.texts),
                    "dim": int(self.embedding_dim),
                    "embedding_fallback": bool(self.embedding_fallback),
                },
            )
        except Exception:
            # 持久化失败不阻断检索，但静默吞掉会导致下次启动重复全量付费 embed
            logger.warning("FAISS 索引持久化失败，下次启动将全量重建", exc_info=True)

    def rebuild(self) -> None:
        with self._lock:
            self._rebuild_locked()
            self._persist_index()

    def _rebuild_locked(self) -> None:
        if len(self.hashes) != len(self.texts):
            self.hashes = [text_hash(text) for text in self.texts]
        if not self.texts:
            self.vectors = np.zeros((0, 0), dtype=np.float32)
            self._index = None
            self.embedding_dim = 0
            self.embedding_fallback = False
            self.embedding_space = self.model_key
            return
        try:
            vectors = self._embed_with_cache()
        except Exception:
            logger.warning("语料 embedding 不可用，成对降级至 hash 检索空间", exc_info=True)
            self._activate_hash_space()
            return
        recovered = self.embedding_fallback
        self._publish_index(self._prepare_index(vectors), fallback=False)
        if recovered:
            logger.info("语料索引恢复至 provider embedding 空间")

    @staticmethod
    def _normalized_vectors(vectors: Any, rows: int, dimension: int | None = None) -> np.ndarray:
        matrix = np.asarray(vectors, dtype=np.float32)
        if (matrix.ndim != 2 or matrix.shape[0] != rows or matrix.shape[1] <= 0
                or not np.isfinite(matrix).all() or (dimension is not None and matrix.shape[1] != dimension)):
            raise ValueError("Embedding batch count, dimension or finite values are invalid")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if not np.isfinite(norms).all():
            raise ValueError("Embedding vector norm is invalid")
        return matrix / np.clip(norms, 1e-12, None)

    def _prepare_index(self, vectors: Any) -> tuple[np.ndarray, Any, int]:
        matrix = self._normalized_vectors(vectors, len(self.texts))
        index = None
        if HAS_FAISS:
            index = faiss.IndexFlatIP(matrix.shape[1])
            index.add(matrix)
        return matrix, index, int(matrix.shape[1])

    def _publish_index(self, candidate: tuple[np.ndarray, Any, int], *, fallback: bool) -> None:
        # Callers hold the RLock; queries cannot observe a half-built candidate.
        self.vectors, self._index, self.embedding_dim = candidate
        self.embedding_fallback = fallback
        self.embedding_space = HASH_EMBEDDING_SPACE if fallback else self.model_key
        interval = max(0.0, self.settings.embedding_recovery_seconds)
        self._next_recovery_at = time.monotonic() + interval if fallback else 0.0

    def _activate_hash_space(self) -> None:
        vectors = self._embed_with_cache(fallback=True)
        self._publish_index(self._prepare_index(vectors), fallback=True)

    def _provider_embed(self, texts: list[str]) -> list:
        from app.services import llm_ledger

        token = llm_ledger.current_purpose.set("embed")
        try:
            return self.provider.embed(texts)
        finally:
            llm_ledger.current_purpose.reset(token)

    def _embed_with_cache(self, *, fallback: bool = False, expected_dim: int | None = None) -> list:
        """Embed only chunks whose text hash is absent from the cache."""
        space = HASH_EMBEDDING_SPACE if fallback else self.model_key
        cache_path = embedding_cache_file(self.cache_dir, space)
        cache = load_embedding_cache(cache_path, space)
        if cache:
            try:
                self._normalized_vectors(list(cache.values()), len(cache), expected_dim)
            except ValueError:
                logger.warning("embedding 缓存形状无效，重新获取当前空间的完整语料")
                cache = {}
        missing = [
            (index, text)
            for index, (item_hash, text) in enumerate(zip(self.hashes, self.texts, strict=False))
            if item_hash not in cache
        ]
        if missing:
            texts = [text for _, text in missing]
            fresh = hash_embed(texts) if fallback else self._provider_embed(texts)
            self._normalized_vectors(fresh, len(missing), expected_dim)
            for (index, _), vector in zip(missing, fresh, strict=True):
                cache[self.hashes[index]] = np.asarray(vector, dtype=np.float32)
        vectors = [cache[item_hash] for item_hash in self.hashes]
        self._normalized_vectors(vectors, len(self.texts), expected_dim)
        if missing:
            save_embedding_cache(cache_path, space, cache)
        return vectors

    def _query_vector(self, query: str) -> np.ndarray:
        if not self.embedding_fallback:
            try:
                return self._normalized_vectors(self._provider_embed([query]), 1, self.embedding_dim)
            except Exception:
                logger.warning("查询 embedding 不可用，语料与查询同时切换 hash 空间", exc_info=True)
                self._activate_hash_space()
                self._persist_index()
        elif time.monotonic() >= self._next_recovery_at:
            try:
                query_vector = self._normalized_vectors(self._provider_embed([query]), 1)
                vectors = self._embed_with_cache(expected_dim=int(query_vector.shape[1]))
                candidate = self._prepare_index(vectors)
                self._publish_index(candidate, fallback=False)
                self._persist_index()
                logger.info("查询与语料校验通过，恢复 provider embedding 空间")
                return query_vector
            except Exception:
                self._next_recovery_at = time.monotonic() + max(0.0, self.settings.embedding_recovery_seconds)
                logger.warning("embedding 恢复探测失败，保留完整 hash 索引", exc_info=True)
        return self._normalized_vectors(hash_embed([query]), 1, self.embedding_dim)

    def search(
        self,
        query: str,
        top_k: int = 5,
        tags: list[str] | None = None,
        *,
        include_demo: bool = False,
        reranker_enabled: bool | None = None,
    ) -> list[dict]:
        with self._lock:
            if not self.texts or top_k <= 0:
                return []
            return self._search_locked(
                query,
                top_k=top_k,
                tags=tags,
                include_demo=include_demo,
                reranker_enabled=reranker_enabled,
            )

    def _search_locked(
        self,
        query: str,
        *,
        top_k: int,
        tags: list[str] | None,
        include_demo: bool,
        reranker_enabled: bool | None,
    ) -> list[dict]:
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
        query_vector = self._query_vector(query)

        if self._index is not None:
            scores, indexes = self._index.search(query_vector, candidate_window)
            pairs = [(int(i), float(s)) for i, s in zip(indexes[0], scores[0], strict=False) if i >= 0]
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
                    "embedding_space": self.embedding_space,
                    "embedding_fallback": self.embedding_fallback,
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
            "embedding_space": item.get("embedding_space", ""),
            "embedding_fallback": bool(item.get("embedding_fallback")),
        }
        for item in retrieval
    ]
