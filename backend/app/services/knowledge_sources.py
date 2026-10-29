"""Watch authoritative source URLs for changes without publishing anything automatically."""

import hashlib
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import KnowledgeSource
from app.models.entities import utcnow
from app.schemas.location import utc_event_time

MAX_SOURCE_BYTES = 2 * 1024 * 1024
FETCH_TIMEOUT = 10.0


class SourceError(Exception):
    pass


def validate_source_url(value: str) -> str:
    url = urlsplit(value.strip())
    if url.scheme not in {"http", "https"} or not url.netloc or url.username or url.password:
        raise SourceError("来源须为可定位的 HTTP(S) 链接")
    return value.strip()


def fetch_content(url: str) -> bytes:
    try:
        with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            content = response.content
    except httpx.HTTPStatusError as exc:
        raise SourceError(f"来源返回 HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise SourceError(f"来源不可达：{type(exc).__name__}") from exc
    if len(content) > MAX_SOURCE_BYTES:
        raise SourceError("来源内容超过 2MB，未记录变化")
    return content


def source_pending(item: KnowledgeSource) -> bool:
    return bool(item.last_hash and item.last_hash != item.acknowledged_hash)


def source_out(item: KnowledgeSource) -> dict:
    return {
        "id": item.id, "name": item.name, "url": item.url, "industry": item.industry,
        "last_status": item.last_status, "last_error": item.last_error,
        "last_checked_at": utc_event_time(item.last_checked_at),
        "change_detected_at": utc_event_time(item.change_detected_at),
        "acknowledged_at": utc_event_time(item.acknowledged_at),
        "pending": source_pending(item),
    }


def create_source(db: Session, name: str, url: str, industry: str) -> KnowledgeSource:
    try:
        validated = validate_source_url(url)
    except SourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    item = KnowledgeSource(name=name, url=validated, industry=industry)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def delete_source(db: Session, item: KnowledgeSource) -> None:
    db.delete(item)
    db.commit()


def check_source(db: Session, item: KnowledgeSource) -> KnowledgeSource:
    item.last_checked_at = utcnow()
    try:
        content = fetch_content(item.url)
    except SourceError as exc:
        item.last_status = "unreachable"
        item.last_error = str(exc)[:300]
        db.commit()
        db.refresh(item)
        return item
    except Exception as exc:  # unexpected fetch failures must stay visible, not crash the check
        item.last_status = "unreachable"
        item.last_error = f"检查失败：{type(exc).__name__}"[:300]
        db.commit()
        db.refresh(item)
        return item
    digest = hashlib.sha256(content).hexdigest()
    item.last_error = None
    if item.last_hash is None:
        item.last_hash = digest
        item.acknowledged_hash = digest
        item.last_status = "ok"
    elif digest != item.last_hash:
        item.last_hash = digest
        item.last_status = "changed"
        item.change_detected_at = utcnow()
    else:
        item.last_status = "changed" if source_pending(item) else "ok"
    db.commit()
    db.refresh(item)
    return item


def acknowledge_source(db: Session, item: KnowledgeSource) -> KnowledgeSource:
    if not item.last_hash:
        raise HTTPException(status_code=409, detail="请先成功检查来源，再确认已阅")
    item.acknowledged_hash = item.last_hash
    item.acknowledged_at = utcnow()
    item.last_status = "ok"
    db.commit()
    db.refresh(item)
    return item
