import json
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.models import Assessment, AssessmentImage, KnowledgeDocument
from app.schemas.assessment import (
    AssessmentOut,
    ConfirmIn,
    DocumentOut,
    FollowupIn,
    HealthOut,
    ProviderInfo,
    RectificationConfirmIn,
)
from app.services.providers import ImageInput, get_provider, get_providers
from app.services.rag import get_rag
from app.services.knowledge import rebuild_knowledge
from app.services.workflow import run_workflow
from app.services.guardrail import (
    detect_image_type,
    inspect_ocr_texts,
    inspect_text,
    validate_uploaded_input,
)

from app.models.entities import utcnow

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
ALLOWED_DOCUMENT_SUFFIXES = {".txt", ".md"}

router = APIRouter(prefix="/api/v1")
settings = get_settings()


def parse_json(text: str | None):
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def to_out(item: Assessment) -> AssessmentOut:
    def image_url(image: AssessmentImage) -> str | None:
        try:
            relative = Path(image.stored_path).relative_to(settings.upload_dir)
            return f"/uploads/{relative.as_posix()}"
        except ValueError:
            return None

    risk = parse_json(item.risk_result_json) or {}
    evidence_judge = parse_json(item.evidence_judge_json)
    ensemble_judge = parse_json(item.ensemble_judge_json) or {}
    return AssessmentOut(
        id=item.id,
        description=item.description,
        status=item.status,
        scene_summary=item.scene_summary,
        hazard_category=item.hazard_category,
        risk_level=item.risk_level,
        confidence=item.confidence,
        conclusion=item.conclusion,
        evidence=parse_json(item.evidence_json) or [],
        evidence_judge=evidence_judge,
        findings=ensemble_judge.get("final_findings") or [],
        report=parse_json(item.report_json),
        followup_questions=parse_json(item.followup_questions_json) or [],
        followup_used=item.followup_used,
        confirmed=item.confirmed,
        rectification_status=item.rectification_status,
        rectification_note=item.rectification_note,
        rectification_score=item.rectification_score,
        rectification_analysis=parse_json(item.rectification_analysis_json),
        rectified_at=item.rectified_at,
        review_reasons=parse_json(item.review_reasons_json) or [],
        awaiting_human_review=item.status == "awaiting_human_review",
        human_review=parse_json(item.human_review_json),
        risk_result=risk or None,
        risk_score=risk.get("risk_score"),
        risk_label=risk.get("risk_level"),
        risk_operational_level=risk.get("operational_level"),
        risk_rule_version=risk.get("rule_version"),
        risk_factors=risk.get("factor_scores") or {},
        risk_evidence_used=risk.get("evidence_used") or [],
        risk_triggered_rules=risk.get("triggered_rules") or [],
        risk_review_suggestion=bool(risk.get("review_suggestion")),
        created_at=item.created_at,
        updated_at=item.updated_at,
        images=[
            {
                "id": image.id,
                "filename": image.filename,
                "mime_type": image.mime_type,
                "size_bytes": image.size_bytes,
                "image_kind": image.image_kind or "original",
                "url": image_url(image),
            }
            for image in item.images
        ],
    )


def images_from_db(
    db: Session,
    assessment_id: str,
    kind: str | None = None,
) -> list[ImageInput]:
    query = select(AssessmentImage).where(AssessmentImage.assessment_id == assessment_id)
    if kind:
        query = query.where(AssessmentImage.image_kind == kind)
    rows = db.scalars(query).all()
    images = []
    for row in rows:
        path = Path(row.stored_path)
        if path.exists():
            images.append(ImageInput(filename=row.filename, path=path, mime_type=row.mime_type))
    return images


def _apply_state(assessment: Assessment, state: dict, db: Session) -> None:
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
    assessment.followup_questions_json = json.dumps(
        state.get("followup_questions", []), ensure_ascii=False
    )


def _reject_uploaded_input(description: str, image_datas: list[bytes]) -> None:
    result = validate_uploaded_input(description, image_datas)
    errors = [item for item in result.violations if item.severity == "error"]
    if errors:
        detail = "；".join(f"{item.code}: {item.message}" for item in errors)
        raise HTTPException(status_code=400, detail=detail)


def _parse_ocr_texts(raw: str) -> list[str]:
    if not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="ocr_texts 必须为 JSON 字符串数组") from None
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise HTTPException(status_code=400, detail="ocr_texts 必须为 JSON 字符串数组")
    return [item for item in parsed if item.strip()]


def _reject_ocr_texts(ocr_texts: list[str]) -> None:
    errors = [
        item
        for item in inspect_ocr_texts(ocr_texts)
        if item.severity == "error"
    ]
    if errors:
        detail = "；".join(f"{item.code}: {item.message}" for item in errors)
        raise HTTPException(status_code=400, detail=detail)


def _reject_text(text: str) -> None:
    errors = [item for item in inspect_text(text or "") if item.severity == "error"]
    if errors:
        detail = "；".join(f"{item.code}: {item.message}" for item in errors)
        raise HTTPException(status_code=400, detail=detail)


def _run_rectification_compare(item: Assessment, db: Session) -> None:
    provider = get_provider()
    originals = images_from_db(db, item.id, kind="original")
    rectifications = images_from_db(db, item.id, kind="rectification")
    try:
        result = provider.compare(
            originals,
            rectifications,
            item.rectification_note or "",
        )
        score = round(
            min(1.0, max(0.0, float(result.get("completion_score", 0.5)))),
            3,
        )
    except Exception as exc:
        result = {
            "summary": f"AI 比对暂不可用：{str(exc)[:120]}",
            "issues": [],
        }
        score = None
    item.rectification_score = score
    item.rectification_analysis_json = json.dumps(result, ensure_ascii=False)
    if score is not None:
        item.rectification_status = "resolved" if score >= 0.8 else "under_review"


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    rag = get_rag()
    return HealthOut(
        status="ok",
        provider=get_provider().name,
        rag_loaded=len(rag.texts) > 0,
        version="0.1.0",
    )


@router.get("/system/provider", response_model=ProviderInfo)
def provider_info() -> ProviderInfo:
    providers = get_providers()
    primary = providers[0]
    return ProviderInfo(
        provider=primary.name,
        vision_model=getattr(primary, "vision_model", "mock"),
        text_model=getattr(primary, "text_model", "mock"),
        embedding_model=getattr(primary, "embedding_model", "hash-embedding"),
        models=[item.describe() for item in providers],
    )


@router.post("/assessments", response_model=AssessmentOut, status_code=201)
async def create_assessment(
    description: Annotated[str, Form()] = "",
    followup_answer: Annotated[str, Form()] = "",
    ocr_texts: Annotated[str, Form()] = "",
    files: Annotated[list[UploadFile] | None, File()] = None,
    db: Session = Depends(get_db),
) -> AssessmentOut:
    file_list = files or []
    if len(file_list) > settings.max_images:
        raise HTTPException(status_code=400, detail=f"最多上传 {settings.max_images} 张图片")

    staged: list[tuple[UploadFile, bytes]] = []
    for upload in file_list:
        data = await upload.read()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(status_code=400, detail="单张图片不能超过 10MB")
        staged.append((upload, data))
    ocr_list = _parse_ocr_texts(ocr_texts)
    _reject_ocr_texts(ocr_list)
    _reject_uploaded_input(description, [data for _, data in staged])

    assessment = Assessment(description=description)
    db.add(assessment)
    db.flush()

    upload_root = settings.upload_dir / assessment.id
    upload_root.mkdir(parents=True, exist_ok=True)
    images: list[ImageInput] = []
    for upload, data in staged:
        original_name = Path(upload.filename or "image.jpg").name
        stored_name = f"{uuid4().hex}_{original_name}"
        target = upload_root / stored_name
        target.write_bytes(data)
        image = AssessmentImage(
            assessment_id=assessment.id,
            filename=original_name,
            stored_path=str(target),
            mime_type=upload.content_type,
            size_bytes=len(data),
        )
        db.add(image)
        images.append(ImageInput(filename=original_name, path=target, mime_type=upload.content_type))

    db.commit()
    try:
        state = run_workflow(
            description=description or "（未填写描述）",
            images=images,
            followup_answer=followup_answer or None,
            followup_used=0,
            ocr_texts=ocr_list,
        )
    except Exception as exc:
        assessment.status = "failed"
        db.commit()
        raise HTTPException(status_code=502, detail=f"研判服务异常：{exc}") from exc
    _apply_state(assessment, state, db)
    db.commit()
    db.refresh(assessment)
    return to_out(assessment)


@router.get("/assessments", response_model=list[AssessmentOut])
def list_assessments(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[AssessmentOut]:
    query = select(Assessment).order_by(Assessment.created_at.desc())
    if status:
        query = query.where(Assessment.status == status)
    query = query.limit(min(limit, 200)).offset(max(0, offset))
    return [to_out(item) for item in db.scalars(query).all()]


@router.get("/assessments/{assessment_id}", response_model=AssessmentOut)
def get_assessment(assessment_id: str, db: Session = Depends(get_db)) -> AssessmentOut:
    item = db.get(Assessment, assessment_id)
    if not item:
        raise HTTPException(status_code=404, detail="研判记录不存在")
    return to_out(item)


@router.post("/assessments/{assessment_id}/followup", response_model=AssessmentOut)
def followup_assessment(
    assessment_id: str,
    payload: FollowupIn,
    db: Session = Depends(get_db),
) -> AssessmentOut:
    item = db.get(Assessment, assessment_id)
    if not item:
        raise HTTPException(status_code=404, detail="研判记录不存在")
    _reject_text(payload.answer)
    if item.followup_used >= settings.max_followups:
        raise HTTPException(status_code=400, detail="已达追问上限")
    try:
        state = run_workflow(
            description=item.description,
            images=images_from_db(db, assessment_id, kind="original"),
            followup_answer=payload.answer,
            followup_used=item.followup_used,
        )
    except Exception as exc:
        item.status = "failed"
        db.commit()
        raise HTTPException(status_code=502, detail=f"研判服务异常：{exc}") from exc
    item.followup_used += 1
    _apply_state(item, state, db)
    db.commit()
    db.refresh(item)
    return to_out(item)


@router.post("/assessments/{assessment_id}/confirm", response_model=AssessmentOut)
def confirm_assessment(
    assessment_id: str,
    payload: ConfirmIn,
    db: Session = Depends(get_db),
) -> AssessmentOut:
    item = db.get(Assessment, assessment_id)
    if not item:
        raise HTTPException(status_code=404, detail="研判记录不存在")
    item.confirmed = payload.confirmed
    edits = payload.edits or {}
    if edits.get("hazard_category"):
        item.hazard_category = str(edits["hazard_category"])
    if edits.get("risk_level") is not None:
        item.risk_level = int(edits["risk_level"])
    if edits.get("conclusion"):
        item.conclusion = str(edits["conclusion"])
    item.status = "confirmed" if payload.confirmed else "needs_review"
    db.commit()
    db.refresh(item)
    return to_out(item)


@router.post("/assessments/{assessment_id}/rectification", response_model=AssessmentOut)
async def submit_rectification(
    assessment_id: str,
    note: Annotated[str, Form()] = "",
    files: Annotated[list[UploadFile] | None, File()] = None,
    db: Session = Depends(get_db),
) -> AssessmentOut:
    item = db.get(Assessment, assessment_id)
    if not item:
        raise HTTPException(status_code=404, detail="研判记录不存在")
    staged: list[tuple[UploadFile, bytes]] = []
    for upload in files or []:
        data = await upload.read()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(status_code=400, detail="单张图片不能超过 10MB")
        staged.append((upload, data))
    _reject_uploaded_input("", [data for _, data in staged])

    upload_root = settings.upload_dir / assessment_id
    upload_root.mkdir(parents=True, exist_ok=True)
    for upload, data in staged:
        original_name = Path(upload.filename or "rectification.jpg").name
        stored_name = f"rect_{uuid4().hex}_{original_name}"
        target = upload_root / stored_name
        target.write_bytes(data)
        db.add(
            AssessmentImage(
                assessment_id=assessment_id,
                filename=original_name,
                stored_path=str(target),
                mime_type=upload.content_type,
                size_bytes=len(data),
                image_kind="rectification",
            )
        )
    item.rectification_status = "under_review"
    if note:
        item.rectification_note = note
    item.rectified_at = utcnow()
    _run_rectification_compare(item, db)
    db.commit()
    db.refresh(item)
    return to_out(item)


@router.post(
    "/assessments/{assessment_id}/rectification/compare",
    response_model=AssessmentOut,
)
def compare_rectification(
    assessment_id: str,
    db: Session = Depends(get_db),
) -> AssessmentOut:
    item = db.get(Assessment, assessment_id)
    if not item:
        raise HTTPException(status_code=404, detail="研判记录不存在")
    _run_rectification_compare(item, db)
    db.commit()
    db.refresh(item)
    return to_out(item)


@router.post(
    "/assessments/{assessment_id}/rectification/confirm",
    response_model=AssessmentOut,
)
def confirm_rectification(
    assessment_id: str,
    payload: RectificationConfirmIn,
    db: Session = Depends(get_db),
) -> AssessmentOut:
    item = db.get(Assessment, assessment_id)
    if not item:
        raise HTTPException(status_code=404, detail="研判记录不存在")
    item.rectification_status = "resolved" if payload.resolved else "under_review"
    if payload.note:
        item.rectification_note = payload.note
    db.commit()
    db.refresh(item)
    return to_out(item)


def _export_content(item: Assessment) -> str:
    report = parse_json(item.report_json) or {}
    work_order = report.get("work_order", {}) or {}
    evidence = parse_json(item.evidence_json) or []
    lines = [
        f"# {work_order.get('title', '隐患研判报告')}",
        "",
        f"- 状态：{item.status}",
        f"- 隐患类别：{item.hazard_category or '未分类'}",
        f"- 风险等级：{item.risk_level or '-'} 级",
        f"- 置信度：{item.confidence or '-'}",
        "",
        "## 研判结论",
        item.conclusion or "",
        "",
        "## 参考依据",
    ]
    for entry in evidence[:5]:
        lines.append(f"- {entry.get('source', '未标注来源')}：{entry.get('text', '')}")
    lines.append("")
    lines.append(report.get("disclaimer", "AI 辅助生成，需人工确认。"))
    return "\n".join(lines)


@router.get("/assessments/{assessment_id}/export")
def export_assessment(assessment_id: str, db: Session = Depends(get_db)) -> JSONResponse:
    item = db.get(Assessment, assessment_id)
    if not item:
        raise HTTPException(status_code=404, detail="研判记录不存在")
    return JSONResponse({"filename": f"{assessment_id}.md", "content": _export_content(item)})


@router.post("/knowledge/documents", response_model=DocumentOut, status_code=201)
async def upload_knowledge_document(
    title: Annotated[str, Form()] = "未命名文档",
    source: Annotated[str, Form()] = "user-upload",
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> KnowledgeDocument:
    data = await file.read()
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=400, detail="文档不能超过 20MB")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_DOCUMENT_SUFFIXES:
        raise HTTPException(status_code=400, detail="仅支持 .txt 或 .md 文本文件")
    text = data.decode("utf-8", errors="ignore")
    _reject_text(text)
    doc = KnowledgeDocument(
        title=title or Path(file.filename or "document.txt").name,
        source=source,
        status="parsed",
        content_text=text.strip(),
        meta_json=json.dumps({"filename": file.filename}, ensure_ascii=False),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    try:
        rebuild_knowledge(db=db)
        doc.status = "indexed"
    except Exception as exc:
        doc.status = "index_error"
        doc.meta_json = json.dumps(
            {
                **(parse_json(doc.meta_json) or {}),
                "index_error": str(exc)[:200],
            },
            ensure_ascii=False,
        )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/knowledge/documents", response_model=list[DocumentOut])
def list_knowledge_documents(db: Session = Depends(get_db)) -> list[KnowledgeDocument]:
    return list(db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc())).all())


@router.get("/knowledge/documents/{document_id}")
def get_knowledge_document(document_id: str, db: Session = Depends(get_db)):
    item = db.get(KnowledgeDocument, document_id)
    if not item:
        raise HTTPException(status_code=404, detail="知识文档不存在")
    return {
        "id": item.id,
        "title": item.title,
        "source": item.source,
        "version": item.version,
        "status": item.status,
        "content": (item.content_text or "")[:3000],
        "created_at": item.created_at,
    }


@router.delete("/knowledge/documents/{document_id}", status_code=204)
def delete_knowledge_document(document_id: str, db: Session = Depends(get_db)) -> Response:
    item = db.get(KnowledgeDocument, document_id)
    if not item:
        raise HTTPException(status_code=404, detail="知识文档不存在")
    db.delete(item)
    db.commit()
    try:
        rebuild_knowledge(db=db)
    except Exception:
        # Deletion is committed; keep the API response stable even if reindex fails.
        pass
    return Response(status_code=204)


@router.post("/knowledge/rebuild")
def rebuild_knowledge_endpoint(db: Session = Depends(get_db)):
    result = rebuild_knowledge(db=db)
    return {
        "chunks": result["chunks"],
        "records": result["records"],
        "embedding_fallback": result["embedding_fallback"],
    }
