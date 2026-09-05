"""Knowledge base chunking and rebuild service."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.core.config import get_settings
from app.services.rag import get_rag

SENTENCE_END = re.compile(r"(?<=[。！？；])")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    meta: dict = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1].strip()
            body = parts[2].strip()
            for line in frontmatter.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()
                if key == "tags":
                    meta[key] = [
                        item.strip()
                        for item in value.strip("[]").split(",")
                        if item.strip()
                    ]
                else:
                    meta[key] = value
    return meta, body


def split_sentences(text: str) -> list[str]:
    parts = SENTENCE_END.split(text)
    return [part.strip() for part in parts if part and part.strip()]


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> list[str]:
    chunks: list[str] = []
    buffer = ""
    for sentence in split_sentences(text):
        while len(sentence) > chunk_size:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            chunks.append(sentence[:chunk_size])
            sentence = sentence[chunk_size:]
        if buffer and len(buffer) + len(sentence) > chunk_size:
            chunks.append(buffer)
            buffer = (buffer[-overlap:] if overlap else "") + sentence
        else:
            buffer += sentence
    if buffer:
        chunks.append(buffer)
    return [chunk for chunk in chunks if chunk.strip()]


def ingest_directory(
    input_dir: Path,
    output_dir: Path,
    chunk_size: int = 400,
    overlap: int = 50,
) -> list[dict]:
    records: list[dict] = []
    for path in sorted(input_dir.glob("*.txt")) + sorted(input_dir.glob("*.md")):
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
        if not body.strip():
            continue
        item_id = meta.get("id") or path.stem
        title = meta.get("title") or path.stem
        for index, chunk in enumerate(chunk_text(body, chunk_size, overlap)):
            records.append(
                {
                    "id": f"{item_id}-chunk-{index}",
                    "title": title,
                    "text": chunk,
                    "source": meta.get("source", "未标注来源"),
                    "version": meta.get("version", ""),
                    "collected_at": meta.get("collected_at", ""),
                    "tags": meta.get("tags", []),
                }
            )
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "real_chunks.jsonl"
    with out_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return records


def rebuild_knowledge() -> dict:
    settings = get_settings()
    records = ingest_directory(
        settings.knowledge_dir / "source_raw",
        settings.knowledge_dir / "chunks",
    )
    rag = get_rag()
    rag.load()
    return {
        "records": len(records),
        "chunks": len(rag.texts),
        "embedding_fallback": rag.embedding_fallback,
    }

