"""Reserve and settle followups in the same transaction as their job changes."""

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import Assessment, AssessmentJob
from app.services.assessment_io import apply_state
from app.services.review import ensure_followup_allowed


def reserve_followup(db: Session, assessment_id: str, maximum: int) -> tuple[Assessment, str]:
    token = str(uuid4())
    active = exists().where(
        AssessmentJob.assessment_id == assessment_id, AssessmentJob.status.in_(["queued", "running"]),
    )
    item = db.scalars(update(Assessment).where(
        Assessment.id == assessment_id, Assessment.status == "needs_more_info",
        Assessment.confirmed.is_(False), Assessment.followup_token.is_(None),
        Assessment.followup_used < maximum, ~active,
    ).values(
        followup_used=Assessment.followup_used + 1, followup_token=token, status="pending",
    ).returning(Assessment).execution_options(populate_existing=True)).first()
    if item is not None:
        return item, token
    item = db.scalar(select(Assessment).where(Assessment.id == assessment_id).execution_options(populate_existing=True))
    if item is None:
        raise HTTPException(status_code=404, detail="研判记录不存在")
    ensure_followup_allowed(item, db)
    if item.followup_used >= maximum:
        raise HTTPException(status_code=400, detail="已达追问上限")
    raise HTTPException(status_code=409, detail="该研判已有追问预留，请等待当前请求结束")


def release_followup(db: Session, assessment_id: str, token: str) -> bool:
    """失败/超时只释放对应预留一次，原始结论和复核数据保持不变。"""
    result = db.execute(update(Assessment).where(
        Assessment.id == assessment_id, Assessment.followup_token == token,
        Assessment.status == "pending", Assessment.confirmed.is_(False), Assessment.followup_used > 0,
    ).values(followup_used=Assessment.followup_used - 1, followup_token=None, status="needs_more_info"))
    return result.rowcount == 1


def finish_followup(db: Session, assessment_id: str, token: str, state: dict) -> bool:
    item = db.scalars(update(Assessment).where(
        Assessment.id == assessment_id, Assessment.followup_token == token,
        Assessment.status == "pending", Assessment.confirmed.is_(False),
    ).values(followup_token=None).returning(Assessment).execution_options(populate_existing=True)).first()
    if item is None:
        return False
    apply_state(item, state, db)
    return True


def recover_abandoned_sync_followups() -> int:
    """单实例启动时回收上个进程未完成的同步追问；活动异步 job 保留预留。"""
    active = exists().where(
        AssessmentJob.assessment_id == Assessment.id, AssessmentJob.status.in_(["queued", "running"]),
    )
    with SessionLocal() as db:
        result = db.execute(update(Assessment).where(
            Assessment.followup_token.is_not(None), Assessment.status == "pending",
            Assessment.confirmed.is_(False), Assessment.followup_used > 0, ~active,
        ).values(status="needs_more_info", followup_token=None, followup_used=Assessment.followup_used - 1))
        db.commit()
        return result.rowcount
