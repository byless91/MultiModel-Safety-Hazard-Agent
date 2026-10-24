"""研判结果的读写共享层：API 路由与异步任务 worker（job_runner）共用。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Assessment, AssessmentImage
from app.services.providers import ImageInput


def images_from_db(
    db: Session,
    assessment_id: str,
    kind: str | None = None,
) -> list[ImageInput]:
    query = select(AssessmentImage).where(AssessmentImage.assessment_id == assessment_id)
    if kind:
        query = query.where(AssessmentImage.image_kind == kind)
    query = query.order_by(AssessmentImage.created_at, AssessmentImage.id)
    rows = db.scalars(query).all()
    images = []
    for row in rows:
        path = Path(row.stored_path)
        if path.exists():
            images.append(ImageInput(filename=row.filename, path=path, mime_type=row.mime_type))
    return images


def apply_state(assessment: Assessment, state: dict, db: Session) -> None:
    """把 workflow 终态写回 assessment 行（JSON 列序列化）。"""
    assessment.status = state.get("status", "completed")
    assessment.scene_summary = state.get("scene_summary")
    assessment.hazard_category = state.get("hazard_category")
    assessment.risk_level = state.get("risk_level")
    assessment.confidence = state.get("confidence")
    assessment.conclusion = state.get("conclusion")
    assessment.evidence_json = json.dumps(state.get("evidence", []), ensure_ascii=False)
    assessment.report_json = (
        json.dumps(state.get("report"), ensure_ascii=False) if state.get("report") else None
    )
    assessment.review_reasons_json = json.dumps(
        state.get("review_reasons", []), ensure_ascii=False
    )
    assessment.human_review_json = (
        json.dumps(state.get("human_review"), ensure_ascii=False)
        if state.get("human_review")
        else None
    )
    risk_result = state.get("risk_result")
    assessment.risk_result_json = (
        json.dumps(risk_result, ensure_ascii=False) if risk_result else None
    )
    if isinstance(risk_result, dict) and risk_result.get("operational_level"):
        assessment.risk_level = int(risk_result["operational_level"])
    assessment.evidence_judge_json = (
        json.dumps(state.get("evidence_judge"), ensure_ascii=False)
        if state.get("evidence_judge")
        else None
    )
    assessment.ensemble_judge_json = (
        json.dumps(state.get("ensemble_judge"), ensure_ascii=False)
        if state.get("ensemble_judge")
        else None
    )
    assessment.multi_model_json = (
        json.dumps(state.get("multi_model"), ensure_ascii=False)
        if state.get("multi_model")
        else None
    )
    assessment.disagreement_json = (
        json.dumps(state.get("disagreement"), ensure_ascii=False)
        if state.get("disagreement")
        else None
    )
    assessment.followup_questions_json = json.dumps(
        state.get("followup_questions", []), ensure_ascii=False
    )


def job_progress_steps() -> list[str]:
    """worker 可观测的研判阶段（前端据此展示进度）。"""
    return ["analyze", "retrieve", "refine", "judge", "evidence", "generate"]


def parse_payload_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}
