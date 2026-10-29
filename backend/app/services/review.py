"""State boundaries for human review and follow-up operations."""

import json
from copy import deepcopy
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Assessment, AssessmentJob
from app.models.entities import utcnow
from app.schemas.assessment import ConfirmIn
from app.schemas.classification import ClassificationData
from app.services.report import build_reviewed_report, human_summary

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
    review = read_object(item.human_review_json)
    resolution = review.get("resolution")
    expected = {"confirmed": payload.confirmed, "reviewer": reviewer,
                "note": payload.note or "", "edits": payload.edits or {}}
    expected_status = "confirmed" if payload.confirmed else "needs_review"
    if (item.status == expected_status and item.confirmed == payload.confirmed and isinstance(resolution, dict)
            and all(resolution.get(key) == value for key, value in expected.items())):
        return True
    if item.confirmed or item.status == "confirmed":
        raise HTTPException(status_code=409, detail="该研判已定稿，不能覆盖原复核结论；请新建关联研判")
    if item.status not in REVIEWABLE_STATUSES:
        raise HTTPException(status_code=409, detail="研判尚未完成或已失败，当前不能人工定稿")
    return False


def read_object(raw: str | None, *, strict: bool = False) -> dict:
    try:
        value = json.loads(raw) if raw else {}
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    if strict:
        raise HTTPException(status_code=409, detail="已有复核记录格式异常，需管理员核查，不能覆盖原记录")
    return {}


def effective_result(item: Assessment) -> dict:
    """Read old edited records consistently, without rewriting their history."""
    original = read_object(item.report_json)
    review = read_object(item.human_review_json)
    if item.record_mode == "classification":
        return {"report": None, "conclusion": item.conclusion, "human_review": review or None}
    resolution = review.get("resolution")
    conclusion = item.conclusion
    if not isinstance(resolution, dict):
        return {"report": original or None, "conclusion": conclusion, "human_review": review or None}
    if "history" not in review:
        review["history"] = [{**deepcopy(resolution), "legacy": True, "snapshots_available": False}]
    if "ai_original" not in review:
        review["ai_original"] = {"available": False, "reason": "历史人工修订前的 AI 快照未保存，无法恢复"}
    edits = resolution.get("edits") or {}
    if (isinstance(edits, dict) and not edits.get("conclusion")
            and (original.get("category") != item.hazard_category or original.get("level") != item.risk_level)):
        conclusion = human_summary(item.hazard_category, item.risk_level)
    try:
        evidence = json.loads(item.evidence_json or "[]")
    except json.JSONDecodeError:
        evidence = []
    report = build_reviewed_report(
        original, category=item.hazard_category, level=item.risk_level, conclusion=conclusion,
        confidence=item.confidence, evidence=evidence if isinstance(evidence, list) else [], confirmed=item.confirmed,
    )
    return {"report": report, "conclusion": conclusion, "human_review": review}


def apply_human_review(
    item: Assessment, db: Session, payload: ConfirmIn, reviewer: str, reviewer_id: str | None,
) -> bool:
    """Append one event with a compare-and-swap write; False means read-only replay."""
    if confirmation_is_replay(item, db, payload, reviewer):
        return False
    is_classification = item.record_mode == "classification"
    if is_classification:
        if payload.edits:
            raise HTTPException(status_code=422, detail="分类记录请先保存人工录入，再进行审核")
        data = ClassificationData.model_validate_json(item.classification_json or "{}")
        if payload.confirmed and (not item.hazard_category or data.revision == 0):
            raise HTTPException(status_code=409, detail="请先保存人工类别和标签，不能直接批准 AI 建议")
    old_json = item.human_review_json
    review = deepcopy(read_object(old_json, strict=True))
    history = review.setdefault("history", [])
    if not isinstance(history, list) or any(not isinstance(event, dict) for event in history):
        raise HTTPException(status_code=409, detail="已有复核历史格式异常，不能覆盖")
    legacy = review.get("resolution")
    if legacy is not None and not isinstance(legacy, dict):
        raise HTTPException(status_code=409, detail="已有复核结论格式异常，不能覆盖")
    if not history and isinstance(legacy, dict):
        history.append({**deepcopy(legacy), "legacy": True, "snapshots_available": False})
    before = {"hazard_category": item.hazard_category, "risk_level": item.risk_level,
              "conclusion": item.conclusion, "status": item.status, "confirmed": item.confirmed}
    if "ai_original" not in review:
        review["ai_original"] = (
            {"available": False, "reason": "历史人工修订前的 AI 快照未保存，无法恢复"}
            if history else {"available": True, **before, "report": read_object(item.report_json),
                             "risk_result": read_object(item.risk_result_json)}
        )
    after = {**before, **payload.edits, "confirmed": payload.confirmed,
             "status": "confirmed" if payload.confirmed else "needs_review"}
    if not payload.edits.get("conclusion") and {"hazard_category", "risk_level"} & payload.edits.keys():
        after["conclusion"] = human_summary(after["hazard_category"], after["risk_level"])
    resolution = {
        "confirmed": payload.confirmed, "reviewer": reviewer, "reviewer_id": reviewer_id,
        "identity_source": "authenticated" if reviewer_id else "client",
        "note": payload.note or "", "edits": payload.edits, "resolved_at": utcnow().isoformat(),
    }
    snapshot_extra = {"tags": data.final_tags} if is_classification else {}
    history.append({"event_id": uuid4().hex, **resolution,
                    "before": {**before, **snapshot_extra}, "after": {**after, **snapshot_extra}})
    review["resolution"] = resolution
    # Build the same effective report used for both new and legacy read paths.
    original_report = read_object(item.report_json)
    try:
        evidence = json.loads(item.evidence_json or "[]")
    except json.JSONDecodeError:
        evidence = []
    report = None if is_classification else build_reviewed_report(
        original_report, category=after["hazard_category"], level=after["risk_level"],
        conclusion=after["conclusion"], confidence=item.confidence,
        evidence=evidence if isinstance(evidence, list) else [], confirmed=payload.confirmed,
    )
    active = select(AssessmentJob.id).where(
        AssessmentJob.assessment_id == item.id, AssessmentJob.status.in_(["queued", "running"]),
    ).exists()
    result = db.execute(
        update(Assessment).where(
            Assessment.id == item.id, Assessment.human_review_json == old_json,
            Assessment.status == item.status, Assessment.confirmed.is_(False), ~active,
        ).values(
            **after, human_review_json=json.dumps(review, ensure_ascii=False),
            report_json=json.dumps(report, ensure_ascii=False) if report else None,
            confirmed_by_id=reviewer_id if payload.confirmed else None,
            confirmed_by_name=(reviewer or None) if payload.confirmed else None,
        ).execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        db.refresh(item)
        if confirmation_is_replay(item, db, payload, reviewer):
            return False
        raise HTTPException(status_code=409, detail="记录已被其他操作更新，请刷新后重新复核")
    db.commit()
    db.refresh(item)
    return True
