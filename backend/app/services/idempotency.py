"""Compare initial submission payloads and recover existing work without calls."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Assessment, IdempotencyKey


def submission_fingerprint(description: str, answer: str, ocr: list[str], files: list[tuple[str, bytes]]) -> str:
    payload = {
        "version": 1, "description": description, "followup_answer": answer, "ocr_texts": ocr,
        "files": [{"filename": name, "sha256": hashlib.sha256(content).hexdigest()} for name, content in files],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def submission_headers(assessment_id: str) -> dict[str, str]:
    return {"Assessment-Id": assessment_id, "Location": f"/api/v1/assessments/{assessment_id}"}


def find_submission(db: Session, key: str, *, fingerprint: str | None = None) -> Assessment | None:
    """fingerprint=None is a read-only lookup, even after the replay window.

    POST preserves the existing terminal-result TTL contract. Pending/failed
    requests never expire into an implicit paid rerun. Expiration deletes only
    the exact old mapping, so competing requests cannot delete a fresh winner.
    """
    for _ in range(3):
        existing = db.get(IdempotencyKey, key, populate_existing=True)
        if existing is None:
            return None
        item = db.get(Assessment, existing.assessment_id, populate_existing=True)
        if item is None:
            raise HTTPException(status_code=410, detail="原提交记录已不存在，请明确新建研判；此 key 不会自动重放")
        created = existing.created_at.replace(tzinfo=UTC) if existing.created_at.tzinfo is None else existing.created_at
        expired = datetime.now(UTC) - created > timedelta(hours=get_settings().idempotency_ttl_hours)
        if fingerprint is not None and expired and item.status not in {"pending", "failed"}:
            result = db.execute(delete(IdempotencyKey).where(
                IdempotencyKey.key == key, IdempotencyKey.assessment_id == existing.assessment_id,
                IdempotencyKey.created_at == existing.created_at,
            ))
            db.commit()
            if result.rowcount == 1:
                return None
            db.rollback()
            continue
        if fingerprint is not None and existing.request_hash != fingerprint:
            detail = ("同一 Idempotency-Key 的提交内容不同，请查询原记录或使用新 key 明确新建研判"
                      if existing.request_hash else "历史 key 缺少提交指纹，请先查询原记录，不能自动重放")
            raise HTTPException(status_code=409, detail=detail, headers=submission_headers(item.id))
        return item
    raise HTTPException(status_code=409, detail="提交标识正在被更新，请稍后查询原提交")
