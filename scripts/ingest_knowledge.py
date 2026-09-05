# -*- coding: utf-8 -*-
"""Parse source_raw regulations, chunk them, and reload the RAG index."""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

DEFAULT_INPUT = BACKEND / "data" / "knowledge" / "source_raw"
DEFAULT_OUTPUT = BACKEND / "data" / "knowledge" / "chunks"
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


def ingest(input_dir: Path, output_dir: Path, chunk_size: int, overlap: int) -> list[dict]:
    records: list[dict] = []
    for path in sorted(input_dir.glob("*.txt")) + sorted(input_dir.glob("*.md")):
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
        if not body.strip():
            continue
        item_id = meta.get("id") or path.stem
        title = meta.get("title") or path.stem
        source = meta.get("source") or "未标注来源"
        version = meta.get("version") or ""
        collected_at = meta.get("collected_at") or ""
        tags = meta.get("tags") or []
        for index, chunk in enumerate(chunk_text(body, chunk_size, overlap)):
            records.append(
                {
                    "id": f"{item_id}-chunk-{index}",
                    "title": title,
                    "text": chunk,
                    "source": source,
                    "version": version,
                    "collected_at": collected_at,
                    "tags": tags,
                }
            )
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "real_chunks.jsonl"
    with out_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return records


def quick_verify() -> None:
    from app.core.config import get_settings
    from app.services.rag import RAGService
    from app.services.providers import get_provider

    settings = get_settings()
    provider = get_provider()
    rag = RAGService(settings, provider)
    print(f"RAG 切片总数：{len(rag.texts)}")
    print(f"向量生成方式：{'fallback hash' if rag.embedding_fallback else 'provider embedding'}")
    for query in ["疏散通道堆放杂物", "安全风险分级管控", "森林防火期内野外用火"]:
        results = rag.search(query, top_k=3)
        if results:
            first = results[0]
            print(f"[{query}] -> {first.get('source')} | {first.get('text', '')[:36]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="清洗法规原文并生成 RAG 知识切片")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="原始文本目录")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="切片输出目录")
    parser.add_argument("--chunk-size", type=int, default=400, help="切片目标长度")
    parser.add_argument("--overlap", type=int, default=50, help="切片重叠长度")
    args = parser.parse_args()

    records = ingest(args.input, args.output, args.chunk_size, args.overlap)
    print(f"生成切片：{len(records)} 条 -> {args.output / 'real_chunks.jsonl'}")
    quick_verify()


if __name__ == "__main__":
    main()

