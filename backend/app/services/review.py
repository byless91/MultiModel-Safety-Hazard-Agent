"""State boundaries for human review and follow-up operations."""

import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Assessment, AssessmentJob
from app.schemas.assessment import ConfirmIn

REVIEWABLE_STATUSES = {"completed", "awaiting_human_review", "needs_review"}


def ensure_no_active_job(item: Assessment, db: Session) -> None:
    active = db.scalar(
        select(AssessmentJob.id)
        .where(AssessmentJob.assessment_id == item.id, AssessmentJob.status.in_(["queued", "running"]))
        .limit(1)
    )
    if active is not None:
        raise HTTPException(status_code=409, detail="该研判仍有排队或执行中的任务，请等待任务结束")


def ensure_followup_allowed(item: Assessment, db: Session) -> None:
    if item.confirmed or item.status != "needs_more_info":
        raise HTTPException(status_code=409, detail="仅等待补充信息的研判可以追问；已确认结果不能直接重写")
    ensure_no_active_job(item, db)


def confirmation_is_replay(item: Assessment, db: Session, payload: ConfirmIn, reviewer: str) -> bool:
    """An identical final approval is a read; a different one cannot overwrite it."""
    ensure_no_active_job(item, db)
    if item.confirmed or item.status == "confirmed":
        try:
            review = json.loads(item.human_review_json or "{}")
        except json.JSONDecodeError:
            review = {}
        resolution = review.get("resolution") if isinstance(review, dict) else None
        expected = {"confirmed": payload.confirmed, "reviewer": reviewer,
                    "note": payload.note or "", "edits": payload.edits or {}}
        if (item.confirmed and item.status == "confirmed" and isinstance(resolution, dict)
                and all(resolution.get(key) == value for key, value in expected.items())):
            return True
        raise HTTPException(status_code=409, detail="该研判已定稿，不能覆盖原复核结论；请新建关联研判")
    if item.status not in REVIEWABLE_STATUSES:
        raise HTTPException(status_code=409, detail="研判尚未完成或已失败，当前不能人工定稿")
    return False
