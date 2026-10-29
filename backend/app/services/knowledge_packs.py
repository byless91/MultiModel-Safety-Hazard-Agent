"""Verified cloud-to-local knowledge packs: approved versions only, checksum-checked imports."""

import hashlib
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import KnowledgeDocument, KnowledgePackImport
from app.models.entities import utcnow
from app.schemas.knowledge import INDUSTRIES
from app.schemas.location import utc_event_time

PACK_FORMAT = "safety-knowledge-pack-v1"
REVIEW_POLICY = "approved_only"
MAX_PACK_BYTES = 8 * 1024 * 1024


def canonical_documents(documents: list[dict]) -> bytes:
    return json.dumps(
        documents, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def manifest_hash(documents: list[dict]) -> str:
    return hashlib.sha256(canonical_documents(documents)).hexdigest()


def export_pack(db: Session) -> dict:
    rows = db.scalars(select(KnowledgeDocument).where(
        KnowledgeDocument.review_status == "approved",
    ).order_by(KnowledgeDocument.created_at, KnowledgeDocument.id)).all()
    latest: dict[str, KnowledgeDocument] = {}
    for item in rows:
        key = item.series_id or item.id
        current = latest.get(key)
        if current is None or (item.created_at, item.id) > (current.created_at, current.id):
            latest[key] = item
    if not latest:
        raise HTTPException(status_code=409, detail="没有可导出的已审核知识版本")
    documents = [{
        "title": item.title, "source": item.source or "", "version": item.version,
        "industry": item.industry, "applicability": item.applicability or "",
        "content_text": item.content_text or "", "content_sha256": item.content_sha256,
        "series_id": item.series_id or item.id, "review_status": "approved",
        "meta_json": item.meta_json, "review_json": item.review_json,
    } for item in latest.values()]
    pack_version = utcnow().strftime("%Y%m%dT%H%M%S%fZ")
    return {
        "format": PACK_FORMAT,
        "pack_version": pack_version,
        "created_at": utcnow().isoformat(),
        "review_policy": REVIEW_POLICY,
        "documents": documents,
        "manifest": {
            "document_count": len(documents),
            "documents_sha256": manifest_hash(documents),
        },
    }


def _reject(message: str) -> None:
    raise HTTPException(status_code=422, detail=message)


def validate_pack(pack: dict) -> tuple[str, str, list[dict]]:
    if not isinstance(pack, dict):
        _reject("知识包格式无效")
    if pack.get("format") != PACK_FORMAT or pack.get("review_policy") != REVIEW_POLICY:
        _reject("知识包格式或审核策略不受支持")
    pack_version = pack.get("pack_version")
    if not isinstance(pack_version, str) or not pack_version.strip() or len(pack_version) > 32:
        _reject("知识包缺少有效版本标识")
    documents = pack.get("documents")
    manifest = pack.get("manifest")
    if not isinstance(documents, list) or not documents:
        _reject("知识包没有文档")
    if not isinstance(manifest, dict):
        _reject("知识包缺少校验清单")
    summary = manifest_hash(documents)
    if len(canonical_documents(documents)) > MAX_PACK_BYTES:
        _reject("知识包超过 8MB，请拆分后导入")
    if manifest.get("document_count") != len(documents) or manifest.get("documents_sha256") != summary:
        _reject("知识包校验失败：文档数量或摘要不一致")
    seen: set[tuple[str, str]] = set()
    normalized = []
    for index, doc in enumerate(documents, start=1):
        if not isinstance(doc, dict):
            _reject(f"第 {index} 个文档格式无效")
        title = doc.get("title")
        version = doc.get("version")
        series_id = doc.get("series_id")
        content = doc.get("content_text")
        content_sha = doc.get("content_sha256")
        industry = doc.get("industry")
        if (not isinstance(title, str) or not title.strip() or len(title) > 255
                or not isinstance(version, str) or not version.strip() or len(version) > 64
                or not isinstance(series_id, str) or not series_id.strip() or len(series_id) > 36
                or not isinstance(content, str) or not content.strip()
                or not isinstance(content_sha, str) or doc.get("review_status") != "approved"):
            _reject(f"第 {index} 个文档缺少必要字段或不是已审核版本")
        if industry not in INDUSTRIES:
            _reject(f"第 {index} 个文档的行业目录无效")
        if hashlib.sha256(content.encode()).hexdigest() != content_sha:
            _reject(f"第 {index} 个文档内容指纹不一致")
        if (series_id, version) in seen:
            _reject(f"知识包内存在重复的文档版本：{title} {version}")
        seen.add((series_id, version))
        review = doc.get("review_json")
        if review is not None:
            try:
                review = json.loads(review) if isinstance(review, str) else review
            except json.JSONDecodeError:
                _reject(f"第 {index} 个文档审核记录无效")
            if not isinstance(review, dict) or not isinstance(review.get("history", []), list) \
                    or any(not isinstance(event, dict) for event in review.get("history", [])):
                _reject(f"第 {index} 个文档审核记录无效")
        meta_json = doc.get("meta_json")
        if meta_json is not None:
            try:
                meta = json.loads(meta_json) if isinstance(meta_json, str) else meta_json
            except json.JSONDecodeError:
                _reject(f"第 {index} 个文档元数据无效")
            if not isinstance(meta, dict) or meta.get("is_demo"):
                _reject(f"第 {index} 个文档是演示资料，不能导入")
            meta_json = json.dumps(meta, ensure_ascii=False)
        normalized.append({
            "title": title.strip(), "version": version.strip(), "series_id": series_id.strip(),
            "source": doc.get("source") or "", "industry": industry,
            "applicability": doc.get("applicability") or "", "content_text": content,
            "content_sha256": content_sha, "meta_json": meta_json,
            "review": review or {},
        })
    return pack_version, summary, normalized


def import_pack(db: Session, pack: dict, actor: str | None) -> dict:
    pack_version, summary, documents = validate_pack(pack)
    imported = skipped = superseded = 0
    failures: list[dict] = []
    try:
        for index, doc in enumerate(documents, start=1):
            existing = db.scalar(select(KnowledgeDocument).where(
                KnowledgeDocument.series_id == doc["series_id"],
                KnowledgeDocument.version == doc["version"],
            ))
            if existing is not None:
                if existing.content_sha256 == doc["content_sha256"]:
                    skipped += 1
                else:
                    failures.append({
                        "index": index, "title": doc["title"],
                        "reason": "本地已存在同系列同版本但内容不同，未覆盖",
                    })
                continue
            older = db.scalars(select(KnowledgeDocument).where(
                KnowledgeDocument.series_id == doc["series_id"],
                KnowledgeDocument.review_status == "approved",
            )).all()
            new_id = str(uuid4())
            for previous in older:
                history = []
                try:
                    previous_review = json.loads(previous.review_json or "{}")
                    history = previous_review.get("history", []) if isinstance(previous_review, dict) else []
                    if not isinstance(history, list):
                        history = []
                except json.JSONDecodeError:
                    previous_review = {}
                if not isinstance(previous_review, dict):
                    previous_review = {}
                history.append({
                    "action": "superseded", "replacement_id": new_id, "actor": "knowledge-pack",
                    "actor_id": None, "at": utcnow().isoformat(),
                    "note": f"导入云端知识包 {pack_version}", "version": previous.version,
                })
                previous_review["history"] = history
                previous_review["revision"] = int(previous_review.get("revision") or 0) + 1
                previous.review_json = json.dumps(previous_review, ensure_ascii=False)
                previous.review_status = "superseded"
            if older:
                db.flush()
            review = doc["review"]
            history = review.get("history", [])
            history.append({
                "action": "approve", "actor": "knowledge-pack", "actor_id": None,
                "identity_source": "cloud-pack", "at": utcnow().isoformat(),
                "note": f"导入云端知识包 {pack_version}；云端审核记录随包保留",
                "source_checked": True, "content_sha256": doc["content_sha256"],
                "version": doc["version"],
            })
            review["history"] = history
            review["revision"] = int(review.get("revision") or 0) + 1
            meta_json = doc["meta_json"]
            db.add(KnowledgeDocument(
                id=new_id, title=doc["title"], source=doc["source"], version=doc["version"],
                industry=doc["industry"], applicability=doc["applicability"],
                review_status="approved", series_id=doc["series_id"], supersedes_id=None,
                content_sha256=doc["content_sha256"], status="parsed", content_text=doc["content_text"],
                meta_json=meta_json, review_json=json.dumps(review, ensure_ascii=False),
            ))
            imported += 1
            superseded += len(older)
        record = KnowledgePackImport(
            pack_version=pack_version, manifest_sha256=summary, imported=imported,
            skipped=skipped, superseded=superseded, failed=len(failures), imported_by=actor,
        )
        db.add(record)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="知识包导入与现有版本冲突，请检查后重试") from exc
    return {
        "pack_version": pack_version, "manifest_sha256": summary, "imported": imported,
        "skipped": skipped, "superseded": superseded, "failed": len(failures), "failures": failures,
    }


def pack_status(db: Session) -> dict | None:
    item = db.scalars(select(KnowledgePackImport).order_by(
        KnowledgePackImport.imported_at.desc(), KnowledgePackImport.id.desc()).limit(1)).first()
    if item is None:
        return None
    return {
        "pack_version": item.pack_version, "manifest_sha256": item.manifest_sha256,
        "imported": item.imported, "skipped": item.skipped, "superseded": item.superseded,
        "failed": item.failed, "imported_by": item.imported_by,
        "imported_at": utc_event_time(item.imported_at),
    }
