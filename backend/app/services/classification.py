"""M1 classification and human entry, reusing assessments, providers and review audit."""

import json
from collections.abc import Callable
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Assessment, AssessmentJob
from app.models.entities import utcnow
from app.schemas.classification import CATEGORIES, TAGS, ClassificationData, ClassificationSaveIn
from app.services import llm_ledger
from app.services.knowledge_versions import search_approved_knowledge
from app.services.providers import ImageInput, get_provider
from app.services.rag import get_rag, retrieval_as_evidence


def run_classification(
    description: str, images: list[ImageInput], *, ocr_texts: list[str] | None = None,
    manual: bool = False, provider=None, rag=None, progress: Callable[[str], None] | None = None,
) -> dict:
    data = ClassificationData(suggestion_status="manual" if manual else "pending")
    summary = None
    evidence = []
    if not manual:
        provider = provider or get_provider()
        data.provider, data.model = provider.name, provider.vision_model
        data.is_demo = provider.name == "mock"
        if progress:
            progress("analyze")
        try:
            token = llm_ledger.current_purpose.set("classification")
            try:
                raw = provider.classify(images, description, ocr_texts=ocr_texts)
            finally:
                llm_ledger.current_purpose.reset(token)
            if not isinstance(raw, dict) or raw.get("parse_failed"):
                raise ValueError("invalid classification response")
            category = raw.get("category")
            data.suggested_category = category if isinstance(category, str) and category in CATEGORIES else None
            data.suggestion_status = "suggested" if data.suggested_category else "unknown"
            if not data.suggested_category:
                data.warnings.append("无法可靠分类，请人工核实并选择类别；这不代表没有隐患")
            tags = raw.get("tags", [])
            if not isinstance(tags, list):
                tags = []
                data.warnings.append("模型标签格式异常，已忽略")
            data.suggested_tags = list(dict.fromkeys(tag for tag in tags if isinstance(tag, str) and tag in TAGS))
            if len(data.suggested_tags) != len(tags):
                data.warnings.append("部分建议标签不在当前体系中，已忽略")
            summary = str(raw.get("scene_summary") or "")[:2000]
            uncertainties = raw.get("uncertainties")
            if isinstance(uncertainties, list):
                data.warnings.extend(str(value)[:300] for value in uncertainties[:8])
        except Exception:
            data.suggestion_status = "failed"
            data.warnings.append("AI 分类调用或结果解析失败，未使用降级建议；可继续人工录入")
        if data.is_demo:
            data.warnings.append("当前为 Mock 演示，不能当作真实图片识别能力")
        if progress:
            progress("retrieve")
        try:
            query = " ".join([description, data.suggested_category or "", *data.suggested_tags])
            rows = search_approved_knowledge(query, rag=rag or get_rag())
            evidence = retrieval_as_evidence(rows)
        except Exception:
            data.warnings.append("条款检索失败，请到知识库核对依据")
    if not evidence:
        data.warnings.append("未找到已审核的有效条款；请核对行业或补充资料，当前材料不能作为法规适用依据")
    data.warnings.append("检索条款仅供核对，相似度不代表条款适用性")
    return {
        "status": "awaiting_human_review", "classification": data.model_dump(),
        "scene_summary": summary, "evidence": evidence,
        "review_reasons": ["请先保存人工分类，再由复核员或管理员审核"],
        "human_review": {"need_human_review": True, "history": []},
    }


def save_classification(
    item: Assessment, db: Session, payload: ClassificationSaveIn, actor: str, actor_id: str | None,
) -> None:
    from app.services.review import ensure_no_active_job, read_object

    ensure_no_active_job(item, db)
    if (item.record_mode != "classification" or item.confirmed
            or item.status not in {"awaiting_human_review", "needs_review"}):
        raise HTTPException(status_code=409, detail="仅未定稿且任务已结束的分类记录可以录入")
    old_json = item.classification_json
    data = ClassificationData.model_validate_json(old_json or "{}")
    if payload.taxonomy_version != data.taxonomy_version or payload.revision != data.revision:
        raise HTTPException(status_code=409, detail="分类记录或体系版本已变化，请刷新后重新录入")
    old_review = item.human_review_json
    review = read_object(old_review, strict=True)
    history = review.setdefault("history", [])
    if not isinstance(history, list):
        raise HTTPException(status_code=409, detail="已有审计记录异常，不能覆盖")
    before = {"hazard_category": item.hazard_category, "risk_level": item.risk_level,
              "conclusion": item.conclusion, "tags": data.final_tags}
    after = {"hazard_category": payload.category, "risk_level": payload.risk_level,
             "conclusion": payload.note or None, "tags": payload.tags}
    if before == after:
        return
    review.setdefault("ai_original", {"available": True, "classification": data.model_dump(),
                                     "hazard_category": None, "risk_level": None})
    history.append({
        "event_id": uuid4().hex, "action": "classification_saved", "confirmed": False,
        "reviewer": actor, "reviewer_id": actor_id, "identity_source": "authenticated" if actor_id else "client",
        "resolved_at": utcnow().isoformat(), "before": before, "after": after,
        "note": payload.note, "edits": {"hazard_category": payload.category, "tags": payload.tags,
                                        "risk_level": payload.risk_level},
    })
    data.final_tags = payload.tags
    data.revision += 1
    active = select(AssessmentJob.id).where(
        AssessmentJob.assessment_id == item.id, AssessmentJob.status.in_(["queued", "running"]),
    ).exists()
    result = db.execute(update(Assessment).where(
        Assessment.id == item.id, Assessment.classification_json == old_json,
        Assessment.human_review_json == old_review, Assessment.status == item.status,
        Assessment.confirmed.is_(False), ~active,
    ).values(
        hazard_category=payload.category, risk_level=payload.risk_level, conclusion=payload.note or None,
        classification_json=data.model_dump_json(), human_review_json=json.dumps(review, ensure_ascii=False),
        status="awaiting_human_review",
    ).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="记录已被更新，请刷新后重新录入")
    db.commit()
    db.refresh(item)
