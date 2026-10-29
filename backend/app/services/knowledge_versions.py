"""Immutable document versions, audited publication and live citation validation."""

import hashlib
import json
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models import Assessment, KnowledgeDocument
from app.models.entities import utcnow
from app.schemas.assessment import DocumentOut
from app.schemas.knowledge import KnowledgeMetadataIn, KnowledgeReviewIn
from app.services.review import read_object


def document_out(item: KnowledgeDocument) -> DocumentOut:
    review = read_object(item.review_json)
    return DocumentOut.model_validate(item).model_copy(update={
        "revision": review.get("revision", 0), "review_history": review.get("history", []),
        "is_demo": bool(read_object(item.meta_json).get("is_demo")),
    })


def document_record(item: KnowledgeDocument) -> dict:
    return {
        "id": item.id, "title": item.title, "document": item.title, "source": item.source,
        "version": item.version, "content_text": item.content_text, "industry": item.industry,
        "applicability": item.applicability, "review_status": item.review_status,
        "content_sha256": item.content_sha256, "series_id": item.series_id,
        "supersedes_id": item.supersedes_id,
        "is_demo": bool(read_object(item.meta_json).get("is_demo")),
        "tags": read_object(item.meta_json).get("tags", []),
    }


def create_document_version(db: Session, data: KnowledgeMetadataIn, body: str, filename: str, suffix: str):
    identity = str(uuid4())
    series = identity
    if data.supersedes_id:
        previous = db.get(KnowledgeDocument, data.supersedes_id)
        if previous is None:
            raise HTTPException(status_code=404, detail="原文档版本不存在")
        if previous.industry != data.industry:
            raise HTTPException(status_code=409, detail="新版本必须保留原文档的行业目录")
        series = previous.series_id or previous.id
        previous.series_id = series
    text = body.strip()
    item = KnowledgeDocument(
        id=identity, title=data.title, source=data.source, version=data.version, industry=data.industry,
        applicability=data.applicability, review_status="unreviewed", series_id=series,
        supersedes_id=data.supersedes_id, content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        status="parsed", content_text=text,
        meta_json=json.dumps({"filename": filename, "source_format": suffix.lstrip("."), "is_demo": data.is_demo}),
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="该文档系列已存在相同版本，请使用新的版本标识") from exc
    db.refresh(item)
    return item


def review_document(db: Session, item: KnowledgeDocument, payload: KnowledgeReviewIn, actor: str, actor_id: str | None):
    """Publish and supersede in one transaction; the partial index fences races."""
    from app.services.rag import is_demo_chunk

    target = {"approve": "approved", "reject": "rejected", "retire": "retired"}[payload.decision]
    original_json = item.review_json
    review = read_object(original_json, strict=True)
    history = review.setdefault("history", [])
    if not isinstance(history, list) or any(not isinstance(event, dict) for event in history):
        raise HTTPException(status_code=409, detail="已有文档审核历史异常，不能覆盖")
    if (item.review_status == target and history and history[-1].get("actor_id") == actor_id
            and history[-1].get("actor") == actor and history[-1].get("note") == payload.note):
        return False
    if payload.revision != review.get("revision", 0):
        raise HTTPException(status_code=409, detail="文档审核状态已变化，请重新查询后审核")
    allowed = {"approve": {"unreviewed"}, "reject": {"unreviewed"}, "retire": {"approved"}}
    if item.review_status not in allowed[payload.decision]:
        raise HTTPException(status_code=409, detail="当前版本不能执行该操作；已退回或停用的内容请创建新版本")
    if payload.decision == "approve":
        url = urlsplit(item.source or "")
        if (url.scheme not in {"http", "https"} or not url.netloc or url.username or url.password
                or not item.applicability.strip() or not item.version or item.version in {"unversioned", "user-upload"}
                or not item.content_sha256):
            raise HTTPException(status_code=422, detail="发布需要可定位的 HTTP(S) 来源、明确版本、适用范围及内容指纹")
        if is_demo_chunk(document_record(item)):
            raise HTTPException(status_code=422, detail="演示或开发资料不能发布为有效条款")
    series = item.series_id or item.id
    try:
        # Every version in the same series locks the same root on PostgreSQL.
        db.execute(select(KnowledgeDocument.id).where(KnowledgeDocument.id == series).with_for_update())
        if payload.decision == "approve":
            older = db.scalars(select(KnowledgeDocument).where(
                KnowledgeDocument.series_id == series, KnowledgeDocument.review_status == "approved",
                KnowledgeDocument.id != item.id,
            )).all()
            for old in older:
                old_review = read_object(old.review_json, strict=True)
                old_review.setdefault("history", []).append({
                    "action": "superseded", "replacement_id": item.id, "actor": actor, "actor_id": actor_id,
                    "at": utcnow().isoformat(), "note": payload.note,
                })
                old_review["revision"] = old_review.get("revision", 0) + 1
                changed = db.execute(update(KnowledgeDocument).where(
                    KnowledgeDocument.id == old.id, KnowledgeDocument.review_json == old.review_json,
                    KnowledgeDocument.review_status == "approved",
                ).values(review_status="superseded", review_json=json.dumps(old_review)).execution_options(
                    synchronize_session=False,
                ))
                if changed.rowcount != 1:
                    raise HTTPException(status_code=409, detail="有效版本已变化，请刷新后重试")
        history.append({"action": payload.decision, "actor": actor, "actor_id": actor_id,
                        "identity_source": "authenticated" if actor_id else "client",
                        "at": utcnow().isoformat(), "note": payload.note, "source_checked": payload.source_checked,
                        "content_sha256": item.content_sha256, "version": item.version})
        review["revision"] = review.get("revision", 0) + 1
        changed = db.execute(update(KnowledgeDocument).where(
            KnowledgeDocument.id == item.id, KnowledgeDocument.review_json == original_json,
            KnowledgeDocument.review_status == item.review_status,
        ).values(review_status=target, review_json=json.dumps(review), series_id=series).execution_options(
            synchronize_session=False,
        ))
        if changed.rowcount != 1:
            raise HTTPException(status_code=409, detail="文档审核状态已变化，请刷新后重试")
        db.commit()
    except (IntegrityError, OperationalError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="同一文档版本正在被更新，请刷新后重试") from exc
    except HTTPException:
        db.rollback()
        raise
    db.refresh(item)
    return True


def ensure_deletable(db: Session, item: KnowledgeDocument) -> None:
    referenced = db.scalar(select(Assessment.id).where(Assessment.evidence_json.contains(item.id)).limit(1))
    child = db.scalar(select(KnowledgeDocument.id).where(KnowledgeDocument.supersedes_id == item.id).limit(1))
    if item.review_status != "unreviewed" or referenced or child:
        raise HTTPException(status_code=409, detail="已审核、已被引用或有后续版本的文档不能删除；请停用有效版本")


def search_approved_knowledge(query: str, *, industry: str | None = None, rag=None) -> list[dict]:
    """Recheck the live DB and exact chunk text: stale/forged indexes cannot publish evidence."""
    from app.core.db import SessionLocal
    from app.services.knowledge import document_to_records
    from app.services.rag import get_rag, is_demo_chunk

    rows = (rag or get_rag()).search(query, top_k=20, include_demo=False, approved_only=True, industry=industry)
    results = []
    with SessionLocal() as db:
        expected = {}
        for row in rows:
            identity = row.get("document_id")
            if not identity:
                continue
            if identity not in expected:
                doc = db.get(KnowledgeDocument, identity)
                if (doc is None or doc.review_status != "approved" or not doc.content_sha256
                        or industry and doc.industry != industry or is_demo_chunk(document_record(doc))
                        or hashlib.sha256((doc.content_text or "").encode()).hexdigest() != doc.content_sha256):
                    expected[identity] = {}
                else:
                    expected[identity] = {chunk["id"]: chunk for chunk in document_to_records(document_record(doc))}
            chunk = expected[identity].get(row.get("id"))
            if not chunk or row.get("text") != chunk["text"] or row.get("content_sha256") != chunk["content_sha256"]:
                continue
            results.append({**row, **chunk, "review_status_at_retrieval": "approved"})
    return results[:5]
