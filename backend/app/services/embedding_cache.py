"""Persistent embedding cache and vector-index persistence helpers.

Restarts and rebuilds must not re-call the embedding API for chunks that have
not changed, so vectors are stored on disk keyed by a hash of their text plus
the embedding model that produced them. A corpus signature lets a persisted
FAISS index be reused verbatim when nothing changed.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import numpy as np

CACHE_VERSION = 1
_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


def text_hash(text: str) -> str:
    """Content hash used as the cache key for one chunk."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def corpus_signature(
    hashes: list[str],
    model_key: str,
    *,
    version: int = CACHE_VERSION,
) -> str:
    """Signature covering the exact corpus and embedding model."""
    digest = hashlib.sha256()
    digest.update(f"v{version}|{model_key}|{len(hashes)}|".encode("utf-8"))
    for item in hashes:
        digest.update(item.encode("utf-8"))
        digest.update(b"|")
    return digest.hexdigest()


def cache_stem(model_key: str) -> str:
    cleaned = _UNSAFE_KEY_CHARS.sub("_", model_key).strip("_")
    return cleaned or "default"


def embedding_cache_file(directory: Path, model_key: str) -> Path:
    return Path(directory) / f"embeddings_{cache_stem(model_key)}.npz"


def index_file(directory: Path) -> Path:
    return Path(directory) / "vector_index.faiss"


def index_meta_file(directory: Path) -> Path:
    return Path(directory) / "vector_index.json"


def load_embedding_cache(path: Path, model_key: str) -> dict[str, np.ndarray]:
    """Return ``{text_hash: vector}``; missing or foreign caches load as empty."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with np.load(path, allow_pickle=False) as data:
            stored_key = str(data["model_key"].item())
            if stored_key != model_key:
                return {}
            hashes = [str(item) for item in data["hashes"]]
            vectors = data["vectors"]
    except (OSError, ValueError, KeyError, EOFError):
        return {}
    if not hashes or len(hashes) != len(vectors):
        return {}
    return {item: vectors[index] for index, item in enumerate(hashes)}


def save_embedding_cache(
    path: Path,
    model_key: str,
    cache: dict[str, np.ndarray],
) -> None:
    """Atomically persist the cache so a crash cannot leave a partial file."""
    if not cache:
        return
    path = Path(path)
    hashes = list(cache.keys())
    vectors = np.asarray([cache[item] for item in hashes], dtype=np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp.npz")
    np.savez_compressed(
        temp_path,
        model_key=np.array(model_key),
        version=np.array(CACHE_VERSION),
        hashes=np.array(hashes),
        vectors=vectors,
    )
    temp_path.replace(path)


def load_index_meta(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_index_meta(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
