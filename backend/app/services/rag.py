import json

import numpy as np

from app.core.config import get_settings
from app.services.providers import get_provider, hash_embed

try:
    import faiss

    HAS_FAISS = True
except Exception:  # faiss is optional; numpy fallback covers small demo corpora
    HAS_FAISS = False


class RAGService:
    def __init__(self, settings, provider) -> None:
        self.settings = settings
        self.provider = provider
        self.texts: list[str] = []
        self.metas: list[dict] = []
        self.vectors = np.zeros((0, 0), dtype=np.float32)
        self._index = None
        self.embedding_fallback = False
        self.load()

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
            }
            for item in chunks
        ]
        self.rebuild()

    def rebuild(self) -> None:
        if not self.texts:
            self.vectors = np.zeros((0, 0), dtype=np.float32)
            self._index = None
            return
        if self.embedding_fallback:
            vectors = hash_embed(self.texts)
        else:
            try:
                vectors = self.provider.embed(self.texts)
                self.embedding_fallback = False
            except Exception:
                self.embedding_fallback = True
                vectors = hash_embed(self.texts)
        self.vectors = np.asarray(vectors, dtype=np.float32)
        self._index = None
        if HAS_FAISS and self.vectors.shape[0] > 0:
            index = faiss.IndexFlatIP(self.vectors.shape[1])
            index.add(self.vectors)
            self._index = index

    def search(self, query: str, top_k: int = 5, tags: list[str] | None = None) -> list[dict]:
        if not self.texts:
            return []
        try:
            if self.embedding_fallback:
                raise RuntimeError("fallback embedding mode")
            query_vector = np.asarray(self.provider.embed([query]), dtype=np.float32)
        except Exception:
            if self.vectors.shape[1] != 256:
                self.embedding_fallback = True
                self.rebuild()
            query_vector = np.asarray(hash_embed([query]), dtype=np.float32)

        if self._index is not None:
            scores, indexes = self._index.search(query_vector, min(top_k * 4, len(self.texts)))
            pairs = [(int(i), float(s)) for i, s in zip(indexes[0], scores[0]) if i >= 0]
        else:
            dots = self.vectors @ query_vector[0]
            order = np.argsort(dots)[::-1]
            pairs = [(int(i), float(dots[i])) for i in order[: top_k * 4]]

        results: list[dict] = []
        seen: set[str] = set()
        for index, score in pairs:
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
            if len(results) >= top_k:
                break
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
