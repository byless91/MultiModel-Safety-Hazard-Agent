"""Knowledge base chunking and rebuild service."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.ensemble.categories import CATEGORY_RAG_TAGS
from app.services.guardrail.input_guard import inspect_text
from app.services.rag import get_rag

SENTENCE_END = re.compile(r"(?<=[。！？；])")
ARTICLE_RE = re.compile(r"第\s*[一二三四五六七八九十百千零〇0-9]+\s*条")
SKIP_SOURCE_FILENAMES = {"sources.md"}

_KNOWN_TAGS = sorted({tag for tags in CATEGORY_RAG_TAGS.values() for tag in tags})


def derive_tags(text: str, limit: int = 8) -> list[str]:
    """Infer retrieval tags from document text.

    Uploaded regulations carry no tag metadata, and tag-filtered retrieval
    otherwise excludes them permanently, so fall back to matching the known
    tag vocabulary against the document body.
    """
    return [tag for tag in _KNOWN_TAGS if tag in text][:limit]


def _knowledge_content_rejected(text: str) -> bool:
    """Injection checks only.

    Documents are bounded by the upload size limit, not by the 2000-character
    cap that applies to a user's short field description. Applying that cap here
    silently dropped every long regulation from the index.
    """
    return any(
        item.severity == "error"
        for item in inspect_text(text, source="knowledge_content", max_length=None)
    )


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


def extract_article(text: str) -> str:
    match = ARTICLE_RE.search(text)
    return match.group(0).replace(" ", "") if match else ""


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


def collect_directory_records(
    input_dir: Path,
    chunk_size: int = 400,
    overlap: int = 50,
) -> list[dict]:
    records: list[dict] = []
    for path in sorted(input_dir.glob("*.txt")) + sorted(input_dir.glob("*.md")):
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
        if path.name in SKIP_SOURCE_FILENAMES or meta.get("index") == "false":
            continue
        if _knowledge_content_rejected(body):
            continue
        if not body.strip():
            continue
        item_id = meta.get("id") or path.stem
        title = meta.get("title") or path.stem
        tags = meta.get("tags") or []
        if not tags:
            tags = derive_tags(body)
        article = meta.get("article") or extract_article(body)
        document = meta.get("document") or title
        risk_type = meta.get("risk_type") or (tags[0] if tags else "")
        scene = meta.get("scene") or (tags[1] if len(tags) > 1 else "")
        effective_date = meta.get("effective_date") or meta.get("collected_at") or ""
        for index, chunk in enumerate(chunk_text(body, chunk_size, overlap)):
            records.append(
                {
                    "id": f"{item_id}-chunk-{index}",
                    "title": title,
                    "document": document,
                    "article": article,
                    "risk_type": risk_type,
                    "scene": scene,
                    "effective_date": effective_date,
                    "text": chunk,
                    "source": meta.get("source", "未标注来源"),
                    "version": meta.get("version", ""),
                    "collected_at": meta.get("collected_at", ""),
                    "tags": meta.get("tags", []),
                    "is_demo": False,
                }
            )
    return records


def ingest_directory(
    input_dir: Path,
    output_dir: Path,
    chunk_size: int = 400,
    overlap: int = 50,
) -> list[dict]:
    records = collect_directory_records(input_dir, chunk_size, overlap)
    write_records(records, output_dir)
    return records


def write_records(records: list[dict], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "real_chunks.jsonl"
    with out_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return out_path


def document_to_records(
    doc: dict[str, Any],
    chunk_size: int = 400,
    overlap: int = 50,
) -> list[dict]:
    """Chunk one knowledge_documents row into traceable RAG records."""
    body = str(doc.get("content_text") or "").strip()
    if not body:
        return []
    if _knowledge_content_rejected(body):
        return []
    title = str(doc.get("title") or "未命名文档")
    article = str(doc.get("article") or extract_article(body))
    tags = [
        str(item)
        for item in list(dict.fromkeys((doc.get("tags") or []) + (doc.get("meta_tags") or [])))
    ]
    if not tags:
        tags = derive_tags(body)
    records: list[dict] = []
    for index, chunk in enumerate(chunk_text(body, chunk_size, overlap)):
        records.append(
            {
                "id": f"doc-{doc.get('id')}-chunk-{index}",
                "title": title,
                "document": str(doc.get("document") or title),
                "article": article,
                "risk_type": str(doc.get("risk_type") or ""),
                "scene": str(doc.get("scene") or ""),
                "effective_date": str(doc.get("effective_date") or ""),
                "text": chunk,
                "source": str(doc.get("source") or "用户上传"),
                "version": str(doc.get("version") or "user-upload"),
                "collected_at": str(doc.get("collected_at") or ""),
                "tags": tags,
                "is_demo": False,
            }
        )
    return records


def rebuild_knowledge(db=None) -> dict:
    settings = get_settings()
    records = collect_directory_records(settings.knowledge_dir / "source_raw")
    if db is not None:
        from sqlalchemy import select

        from app.models import KnowledgeDocument

        for doc in db.scalars(select(KnowledgeDocument)).all():
            meta: dict[str, Any] = {}
            if doc.meta_json:
                try:
                    parsed = json.loads(doc.meta_json)
                    if isinstance(parsed, dict):
                        meta = parsed
                except json.JSONDecodeError:
                    pass
            records.extend(
                document_to_records(
                    {
                        "id": doc.id,
                        "title": doc.title,
                        "document": doc.title,
                        "source": doc.source or "用户上传",
                        "version": doc.version or "user-upload",
                        "content_text": doc.content_text or "",
                        "tags": meta.get("tags") if isinstance(meta.get("tags"), list) else [],
                    }
                )
            )
    write_records(records, settings.knowledge_dir / "chunks")
    rag = get_rag()
    rag.load()
    return {
        "records": len(records),
        "chunks": len(rag.texts),
        "embedding_fallback": rag.embedding_fallback,
    }
