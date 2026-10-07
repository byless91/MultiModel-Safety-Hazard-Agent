import json
import re
import tempfile
from pathlib import Path
from typing import Annotated, Any
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
    RectificationTransitionIn,
)
from app.services.providers import ImageInput, get_provider, get_providers
from app.services.rag import get_rag
from app.services.knowledge import rebuild_knowledge
from app.services.rectification import (
    RectificationTransitionError,
    next_rectification_states,
    normalize_rectification_status,
    rectification_state_label,
    submit_rectification_photos,
    transition_rectification,
)
from app.services.rectification_assessment import assess_rectification_completion
from app.services.workflow import run_workflow
from app.services.guardrail import (
    detect_image_type,
    inspect_ocr_texts,
    inspect_text,
    validate_uploaded_input,
)
from app.services.document_converter import (
    LEGACY_SUFFIX_HINTS,
    PLAIN_SUFFIXES,
    SUPPORTED_SUFFIXES,
    ConversionError,
    convert_to_markdown,
)

from app.models.entities import utcnow

settings = get_settings()

MAX_FILE_BYTES = settings.max_file_bytes
MAX_DOCUMENT_BYTES = settings.max_document_bytes
ALLOWED_DOCUMENT_SUFFIXES = set(SUPPORTED_SUFFIXES)
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
UNSAFE_FILENAME_RE = re.compile(
    r"(\.\./|\.\.\\|[/\\]{2}|[\x00-\x1f]|^[A-Za-z]:[\\/])"
)

router = APIRouter(prefix="/api/v1")


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
    rect_status = normalize_rectification_status(item.rectification_status)
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
        multi_model=parse_json(item.multi_model_json),
        disagreement=parse_json(item.disagreement_json),
        findings=ensemble_judge.get("final_findings") or [],
        report=parse_json(item.report_json),
        followup_questions=parse_json(item.followup_questions_json) or [],
        followup_used=item.followup_used,
        confirmed=item.confirmed,
        rectification_status=rect_status,
        rectification_note=item.rectification_note,
        rectification_score=item.rectification_score,
        rectification_analysis=parse_json(item.rectification_analysis_json),
        rectification_meta=parse_json(item.rectification_meta_json),
        rectification_next_states=next_rectification_states(rect_status),
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
                "created_at": image.created_at,
                "url": image_url(image),
            }
            for image in sorted(
                item.images,
                key=lambda img: (
                    img.created_at.isoformat() if img.created_at else "",
                    img.id,
                ),
            )
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
    query = query.order_by(AssessmentImage.created_at, AssessmentImage.id)
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


def _reject_uploaded_input(description: str, image_datas: list[bytes]) -> None:
    result = validate_uploaded_input(description, image_datas)
    errors = [item for item in result.violations if item.severity == "error"]
    if errors:
        detail = "；".join(f"{item.code}: {item.message}" for item in errors)
        raise HTTPException(status_code=400, detail=detail)


def _safe_filename(filename: str, *, allowed_suffixes: set[str], default: str) -> tuple[str, str]:
    """Return (safe basename, suffix); raise 400 on traversal/odd filenames."""
    raw = filename or ""
    if not raw or raw in (".", ".."):
        raise HTTPException(status_code=400, detail="文件名不能为空")
    if UNSAFE_FILENAME_RE.search(raw):
        raise HTTPException(status_code=400, detail="文件名包含不安全字符或路径穿越")
    name = Path(raw).name
    if name in (".", ".."):
        raise HTTPException(status_code=400, detail="文件名不能包含路径穿越")
    suffix = Path(name).suffix.lower()
    if suffix not in allowed_suffixes:
        allowed = "、".join(sorted(allowed_suffixes))
        raise HTTPException(status_code=400, detail=f"文件类型不支持，仅允许 {allowed}")
    if not name.replace(suffix, "").strip():
        raise HTTPException(status_code=400, detail="文件名不能只有扩展名")
    return name, suffix


async def _extract_document_text(data: bytes, suffix: str) -> str:
    """Return plain text/Markdown for an uploaded knowledge document.

    Plain text and Markdown are decoded directly; PDF/Word go through the
    MarkItDown converter, which runs off the event loop with its own timeout.
    """
    if suffix in PLAIN_SUFFIXES:
        return data.decode("utf-8", errors="ignore")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            handle.write(data)
            temp_path = Path(handle.name)
        return await convert_to_markdown(temp_path)
    except ConversionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


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


def _reject_text(text: str, *, max_length: int | None = None) -> None:
    errors = [
        item
        for item in inspect_text(text or "", max_length=max_length)
        if item.severity == "error"
    ]
    if errors:
        detail = "；".join(f"{item.code}: {item.message}" for item in errors)
        raise HTTPException(status_code=400, detail=detail)


def _image_row_url(row: AssessmentImage) -> str | None:
    try:
        relative = Path(row.stored_path).relative_to(settings.upload_dir)
        return f"/uploads/{relative.as_posix()}"
    except ValueError:
        return None


def _rectification_image_rows(
    db: Session,
    assessment_id: str,
    kind: str,
) -> list[AssessmentImage]:
    query = (
        select(AssessmentImage)
        .where(
            AssessmentImage.assessment_id == assessment_id,
            AssessmentImage.image_kind == kind,
        )
        .order_by(AssessmentImage.created_at, AssessmentImage.id)
    )
    return list(db.scalars(query).all())


def _comparison_meta(
    original_rows: list[AssessmentImage],
    rectification_rows: list[AssessmentImage],
) -> dict[str, Any]:
    pair_count = min(len(original_rows), len(rectification_rows))
    return {
        "original_count": len(original_rows),
        "rectification_count": len(rectification_rows),
        "pair_count": pair_count,
        "unmatched_original_count": len(original_rows) - pair_count,
        "unmatched_rectification_count": len(rectification_rows) - pair_count,
        "paired": [
            {
                "index": index,
                "original_id": original_rows[index].id,
                "rectification_id": rectification_rows[index].id,
                "original_url": _image_row_url(original_rows[index]),
                "rectification_url": _image_row_url(rectification_rows[index]),
            }
            for index in range(pair_count)
        ],
    }


def _run_rectification_compare(item: Assessment, db: Session) -> None:
    provider = get_provider()
    original_rows = _rectification_image_rows(db, item.id, "original")
    rectification_rows = _rectification_image_rows(db, item.id, "rectification")
    originals = [
        ImageInput(
            filename=row.filename,
            path=Path(row.stored_path),
            mime_type=row.mime_type,
        )
        for row in original_rows
        if Path(row.stored_path).exists()
    ]
    rectifications = [
        ImageInput(
            filename=row.filename,
            path=Path(row.stored_path),
            mime_type=row.mime_type,
        )
        for row in rectification_rows
        if Path(row.stored_path).exists()
    ]
    comparison = _comparison_meta(original_rows, rectification_rows)
    if not rectifications:
        item.rectification_score = None
        assessment = assess_rectification_completion(
            comparison=comparison
        )
        item.rectification_analysis_json = json.dumps(
            {
                "summary": "暂无整改后照片，无法进行前后对比。",
                "issues": ["需要至少上传一张整改后照片"],
                "comparison": comparison,
                "assessment": assessment.model_dump(),
            },
            ensure_ascii=False,
        )
        return
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
            "issues": ["AI 前后对比服务暂不可用"],
        }
        score = None
    if not originals:
        result.setdefault("issues", []).append("缺少整改前照片，AI 前后对比置信度受限")
    result["comparison"] = comparison
    assessment = assess_rectification_completion(
        provider_result=result if score is not None else None,
        comparison=comparison,
        provider_failed=score is None,
    )
    result["assessment"] = assessment.model_dump()
    item.rectification_score = score
    item.rectification_analysis_json = json.dumps(result, ensure_ascii=False)


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    rag = get_rag()
    return HealthOut(
        status="ok",
        provider=get_provider().name,
        rag_loaded=len(rag.texts) > 0,
        reranker_enabled=rag.reranker_enabled,
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


def load_evaluation_reports(eval_dir: Path | None = None) -> dict | None:
    """Load latest evaluation reports; None when nothing has been generated."""
    eval_dir = eval_dir or (Path(__file__).resolve().parents[2] / "data" / "eval")
    evaluation_report = eval_dir / "report.json"
    ablation_report = eval_dir / "ablation_report.json"
    evaluation_results = eval_dir / "results.jsonl"
    ablation_results = eval_dir / "ablation_results.jsonl"

    def _load_json(path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _file_modified(path: Path) -> str | None:
        if not path.exists():
            return None
        from datetime import datetime

        return datetime.fromtimestamp(path.stat().st_mtime).isoformat()

    evaluation_payload = _load_json(evaluation_report)
    if isinstance(evaluation_payload, dict) and not evaluation_payload.get("metrics"):
        metric_keys = [
            "total",
            "category_accuracy",
            "level_accuracy",
            "severity_mae",
            "level_accuracy_tolerance1",
            "clause_hit_rate",
            "evidence_hit_rate",
            "evidence_support_rate",
            "unsupported_claim_rate",
            "model_conflict_rate",
            "human_review_rate",
            "human_review_count",
            "unsafe_auto_pass_count",
            "unsafe_auto_pass_rate",
            "unsafe_hazard_base_count",
            "false_positive_count",
            "false_negative_count",
            "evidence_failure_count",
            "severity_error_count",
            "model_conflict_count",
            "avg_latency_s",
        ]
        evaluation_payload["metrics"] = {
            key: evaluation_payload.get(key) for key in metric_keys
        }
    payload = {
        "evaluation_report": evaluation_payload,
        "ablation_report": _load_json(ablation_report),
        "evaluation_report_modified_at": _file_modified(evaluation_report),
        "ablation_report_modified_at": _file_modified(ablation_report),
        "has_trace_results": evaluation_results.exists() or ablation_results.exists(),
        "source_dir": str(eval_dir),
    }
    if not payload["evaluation_report"] and not payload["ablation_report"]:
        return None
    return payload


@router.get("/evaluation/reports")
def evaluation_reports() -> dict:
    """Serve the latest formal evaluation reports (read-only)."""
    payload = load_evaluation_reports()
    if payload is None:
        raise HTTPException(status_code=404, detail="尚未生成评测报告，请先运行评测脚本")
    return payload


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
        original_name, _suffix = _safe_filename(
            upload.filename or "image.jpg",
            allowed_suffixes=ALLOWED_IMAGE_SUFFIXES,
            default="image.jpg",
        )
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
    human_review = parse_json(item.human_review_json) or {}
    human_review["resolution"] = {
        "confirmed": payload.confirmed,
        "reviewer": payload.reviewer or "",
        "note": payload.note or "",
        "edits": payload.edits or {},
        "resolved_at": utcnow().isoformat(),
    }
    item.human_review_json = json.dumps(human_review, ensure_ascii=False)
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
    current_status = normalize_rectification_status(item.rectification_status)
    if current_status not in ("open", "assigned", "rectifying"):
        raise HTTPException(
            status_code=409,
            detail=f"当前整改状态为“{rectification_state_label(current_status)}”，不允许提交整改照片",
        )
    staged: list[tuple[UploadFile, bytes]] = []
    for upload in files or []:
        data = await upload.read()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(status_code=400, detail="单张图片不能超过 10MB")
        staged.append((upload, data))
    if not staged:
        raise HTTPException(status_code=400, detail="至少需要上传一张整改后照片")
    _reject_uploaded_input("", [data for _, data in staged])

    upload_root = settings.upload_dir / assessment_id
    upload_root.mkdir(parents=True, exist_ok=True)
    for upload, data in staged:
        original_name, _suffix = _safe_filename(
            upload.filename or "rectification.jpg",
            allowed_suffixes=ALLOWED_IMAGE_SUFFIXES,
            default="rectification.jpg",
        )
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
    db.flush()
    submit_rectification_photos(
        item,
        note=note or "提交整改照片并进入人工验证",
        by="user",
    )
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
    target = "verified" if payload.resolved else "rectifying"
    note = payload.note or (
        "人工确认整改完成" if payload.resolved else "人工退回整改"
    )
    try:
        transition_rectification(item, target, note=note, by="user")
    except RectificationTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if payload.note:
        item.rectification_note = payload.note
    db.commit()
    db.refresh(item)
    return to_out(item)


@router.post(
    "/assessments/{assessment_id}/rectification/transition",
    response_model=AssessmentOut,
)
def transition_rectification_status(
    assessment_id: str,
    payload: RectificationTransitionIn,
    db: Session = Depends(get_db),
) -> AssessmentOut:
    item = db.get(Assessment, assessment_id)
    if not item:
        raise HTTPException(status_code=404, detail="研判记录不存在")
    try:
        transition_rectification(
            item,
            payload.to_status,
            note=payload.note,
            by=payload.by or "user",
        )
    except RectificationTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    raw_name = file.filename or "document.txt"
    legacy_hint = LEGACY_SUFFIX_HINTS.get(Path(raw_name).suffix.lower())
    if legacy_hint:
        raise HTTPException(status_code=400, detail=legacy_hint)
    original_name, suffix = _safe_filename(
        raw_name,
        allowed_suffixes=ALLOWED_DOCUMENT_SUFFIXES,
        default="document.txt",
    )
    text = await _extract_document_text(data, suffix)
    # 知识库文档只做注入防护，不套用用户描述的 2000 字限制；
    # 文件大小上限由 MAX_DOCUMENT_BYTES 控制。
    _reject_text(text, max_length=None)
    doc = KnowledgeDocument(
        title=title or original_name,
        source=source,
        status="parsed",
        content_text=text.strip(),
        meta_json=json.dumps(
            {"filename": original_name, "source_format": suffix.lstrip(".")},
            ensure_ascii=False,
        ),
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
