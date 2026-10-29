import json
import logging
import re
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import ValidationError
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.core.security import (
    ALL_ROLES,
    authenticate,
    create_access_token,
    get_request_user,
    hash_password,
    require_roles,
    sign_upload_url,
    verify_password,
)
from app.models import (
    Assessment,
    AssessmentImage,
    AssessmentJob,
    IdempotencyKey,
    KnowledgeDocument,
    KnowledgeSource,
    TrendAlert,
    User,
)
from app.models.entities import utcnow
from app.schemas.analytics import AnalyticsOptionsOut, AnalyticsOverviewOut, BenchmarksOut
from app.schemas.assessment import (
    AssessmentOut,
    AuthUserOut,
    ConfirmIn,
    DocumentOut,
    FollowupIn,
    HealthOut,
    JobOut,
    ProviderInfo,
    RectificationConfirmIn,
    RectificationTransitionIn,
    TokenOut,
    UserAdminOut,
    UserCreateIn,
)
from app.schemas.classification import CATEGORIES, TAGS, TAXONOMY_VERSION, ClassificationData, ClassificationSaveIn
from app.schemas.knowledge import INDUSTRIES, Industry, KnowledgeMetadataIn, KnowledgeReviewIn
from app.schemas.location import ImportResultOut, ImportRowsIn, LocationData, utc_event_time
from app.schemas.updates import AlertOut, AlertReviewIn, SourceIn, SourceOut, TrendReportOut
from app.services import llm_ledger
from app.services.analytics import analytics_benchmarks, analytics_options, analytics_overview
from app.services.assessment_io import apply_state, images_from_db
from app.services.classification import save_classification
from app.services.document_converter import (
    LEGACY_SUFFIX_HINTS,
    PLAIN_SUFFIXES,
    SUPPORTED_SUFFIXES,
    ConversionError,
    convert_to_markdown,
)
from app.services.finding_identity import legacy_evidence_view
from app.services.followup import finish_followup, release_followup, reserve_followup
from app.services.guardrail import (
    detect_image_type,
    inspect_ocr_texts,
    validate_uploaded_input,
)
from app.services.guardrail.input_guard import MAX_DESCRIPTION_LENGTH
from app.services.idempotency import find_submission, submission_fingerprint, submission_headers
from app.services.imports import import_rows
from app.services.job_runner import (
    enqueue_job,
    find_create_thread_id,
    get_job_runner,
)
from app.services.knowledge import document_to_records, rebuild_knowledge
from app.services.knowledge_sources import (
    acknowledge_source,
    check_source,
    create_source,
    delete_source,
    source_out,
)
from app.services.knowledge_versions import (
    create_document_version,
    delete_document_version,
    document_out,
    document_record,
    review_document,
    search_approved_knowledge,
)
from app.services.model_inputs import require_model_text
from app.services.providers import ImageInput, get_provider, get_providers
from app.services.rag import get_rag
from app.services.readiness import readiness_report
from app.services.rectification import (
    RectificationTransitionError,
    next_rectification_states,
    normalize_rectification_status,
    rectification_state_label,
    submit_rectification_photos,
    transition_rectification,
)
from app.services.rectification_assessment import assess_rectification_completion
from app.services.review import apply_human_review, effective_result
from app.services.trends import alert_out, refresh_alerts, review_alert, trend_report
from app.services.workflow import run_workflow

settings = get_settings()
logger = logging.getLogger("safety_hazard.api")

ALLOWED_DOCUMENT_SUFFIXES = set(SUPPORTED_SUFFIXES)
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_ASSESSMENT_STATUSES = {
    "pending",
    "needs_more_info",
    "awaiting_human_review",
    "completed",
    "needs_review",
    "confirmed",
    "failed",
}
UPLOAD_READ_CHUNK = 1024 * 1024
_IMAGE_MIME_BY_KIND = {
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}
UNSAFE_FILENAME_RE = re.compile(
    r"(\.\./|\.\.\\|[/\\]{2}|[\x00-\x1f]|^[A-Za-z]:[\\/])"
)

# guarded：全部业务路由经 authenticate 守卫（none 模式放行）
router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticate)])
# public：健康检查与登录换 token
public_router = APIRouter(prefix="/api/v1")


def parse_json(text: str | None):
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def location_precision(item: Assessment) -> str:
    if item.latitude is not None and item.longitude is not None:
        return "coordinate"
    if item.address:
        return "address"
    if item.district:
        return "district"
    return "unknown"


def to_out(item: Assessment) -> AssessmentOut:
    def image_url(image: AssessmentImage) -> str | None:
        try:
            relative = Path(image.stored_path).relative_to(settings.upload_dir)
            return sign_upload_url(f"/uploads/{relative.as_posix()}")
        except ValueError:
            return None

    risk = parse_json(item.risk_result_json) or {}
    evidence_judge = parse_json(item.evidence_judge_json)
    ensemble_judge = parse_json(item.ensemble_judge_json) or {}
    findings, evidence_judge, identity_warnings = legacy_evidence_view(
        ensemble_judge.get("final_findings") or [], evidence_judge,
    )
    rect_status = normalize_rectification_status(item.rectification_status)
    effective = effective_result(item)
    return AssessmentOut(
        id=item.id,
        description=item.description,
        status=item.status,
        record_mode=item.record_mode,
        address=item.address,
        district=item.district,
        facility=item.facility,
        scene=item.scene,
        latitude=item.latitude,
        longitude=item.longitude,
        coordinate_source=item.coordinate_source,
        coordinate_system=item.coordinate_system,
        data_source=item.data_source,
        event_time=utc_event_time(item.event_time),
        source_ref=item.source_ref,
        import_batch_id=item.import_batch_id,
        location_precision=location_precision(item),
        classification=parse_json(item.classification_json),
        scene_summary=item.scene_summary,
        hazard_category=item.hazard_category,
        risk_level=item.risk_level,
        confidence=item.confidence,
        conclusion=effective["conclusion"],
        evidence=parse_json(item.evidence_json) or [],
        evidence_judge=evidence_judge,
        multi_model=parse_json(item.multi_model_json),
        disagreement=parse_json(item.disagreement_json),
        findings=findings,
        report=effective["report"],
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
        review_reasons=list(dict.fromkeys((parse_json(item.review_reasons_json) or []) + identity_warnings)),
        awaiting_human_review=item.status == "awaiting_human_review",
        human_review=effective["human_review"],
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


async def _read_upload_limited(
    upload: UploadFile, *, max_bytes: int, detail: str
) -> bytes:
    """分块读取上传内容并在超限时立即拒绝，避免大文件整段读入内存后才校验。"""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(UPLOAD_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=400, detail=detail)
        chunks.append(chunk)
    return b"".join(chunks)


def _sniffed_image_mime(data: bytes) -> str:
    """以文件内容（magic bytes）推断 MIME，不信任客户端声明的 content_type。"""
    kind = detect_image_type(data)
    return _IMAGE_MIME_BY_KIND.get(kind or "", "application/octet-stream")


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


def _reject_text(text: str, *, max_length: int | None = MAX_DESCRIPTION_LENGTH) -> None:
    try:
        require_model_text(text or "", max_length=max_length)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _image_row_url(row: AssessmentImage) -> str | None:
    try:
        relative = Path(row.stored_path).relative_to(settings.upload_dir)
        return sign_upload_url(f"/uploads/{relative.as_posix()}")
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


def _record_compare_meta(item: Assessment) -> None:
    """记录最近一次 AI 比对的时间与当时的整改状态，用于窗口内去重。"""
    meta = parse_json(item.rectification_meta_json) or {}
    meta["last_compare_at"] = utcnow().isoformat()
    meta["last_compare_rectification_status"] = normalize_rectification_status(
        item.rectification_status
    )
    item.rectification_meta_json = json.dumps(meta, ensure_ascii=False)


def _compare_recently_run(item: Assessment) -> bool:
    """同整改状态下窗口内的重复比对直接复用缓存结果，不再重复调用模型。"""
    meta = parse_json(item.rectification_meta_json) or {}
    last_at = meta.get("last_compare_at")
    last_status = meta.get("last_compare_rectification_status")
    if not last_at or not item.rectification_analysis_json:
        return False
    if last_status != normalize_rectification_status(item.rectification_status):
        return False
    try:
        last_dt = datetime.fromisoformat(str(last_at))
    except ValueError:
        return False
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=UTC)
    window = timedelta(minutes=settings.compare_dedup_minutes)
    return datetime.now(UTC) - last_dt < window


def _run_rectification_compare(item: Assessment, db: Session) -> None:
    _reject_text(item.rectification_note or "")
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
        _record_compare_meta(item)
        return
    try:
        purpose_token = llm_ledger.current_purpose.set("compare")
        ctx_token = llm_ledger.current_assessment_id.set(item.id)
        try:
            result = provider.compare(
                originals,
                rectifications,
                item.rectification_note or "",
            )
        finally:
            llm_ledger.current_purpose.reset(purpose_token)
            llm_ledger.current_assessment_id.reset(ctx_token)
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
    _record_compare_meta(item)


@public_router.get("/live")
def liveness() -> dict:
    return {"status": "alive"}


@public_router.get("/ready")
def readiness() -> JSONResponse:
    report = readiness_report()
    return JSONResponse(report, status_code=200 if report["status"] == "ready" else 503,
                        headers={"Cache-Control": "no-store"})


@public_router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    rag = get_rag()
    return HealthOut(
        status="ok",
        provider=get_provider().name,
        rag_loaded=len(rag.texts) > 0,
        reranker_enabled=rag.reranker_enabled,
        version=settings.app_version,
        auth_required=settings.auth_mode != "none",
        auth_mode=settings.auth_mode,
    )


@public_router.post("/auth/token", response_model=TokenOut)
@limiter.limit(lambda: f"{get_settings().rate_limit_login_per_minute}/minute", key_func=get_remote_address)
def login(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Session = Depends(get_db),
) -> TokenOut:
    """OAuth2 密码流登录：换取 JWT。失败统一 401，不暴露用户是否存在。"""
    if settings.auth_mode != "jwt":
        raise HTTPException(status_code=409,
                            detail="当前认证模式不提供用户名密码登录；静态凭证模式请使用运维提供的 Bearer 凭证")
    user = db.scalars(select(User).where(User.username == form.username)).first()
    if user is None or user.disabled or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return TokenOut(
        access_token=create_access_token(user),
        user=AuthUserOut(id=user.id, username=user.username, role=user.role),
    )


@router.get("/auth/check")
def check_auth() -> dict:
    return {"auth_mode": settings.auth_mode, "authenticated": settings.auth_mode != "none"}


@router.get("/auth/me", response_model=AuthUserOut)
def whoami(request: Request) -> AuthUserOut:
    user = get_request_user(request)
    if user is None:
        raise HTTPException(status_code=403, detail="当前未启用用户体系")
    return AuthUserOut(id=user.id, username=user.username, role=user.role)


@router.get(
    "/admin/users",
    response_model=list[UserAdminOut],
    dependencies=[Depends(require_roles("admin"))],
)
def list_users(db: Session = Depends(get_db)) -> list[UserAdminOut]:
    users = db.scalars(select(User).order_by(User.created_at)).all()
    # UserAdminOut 不含 password_hash，绝不可把哈希带出服务端
    return [
        UserAdminOut(
            id=u.id,
            username=u.username,
            role=u.role,
            disabled=u.disabled,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.get(
    "/admin/llm-usage",
    dependencies=[Depends(require_roles("admin"))],
)
def llm_usage(days: int = 7) -> dict:
    """LLM 台账聚合视图（B5/WP3.2）：按天×provider×purpose 的调用量与 token 消耗。"""
    days = max(1, min(days, 90))
    return {
        "days": days,
        "tokens_used_today": llm_ledger.tokens_used_today(),
        "daily_token_budget": settings.daily_token_budget,
        "items": llm_ledger.usage_summary(days=days),
    }


@router.post(
    "/admin/users",
    response_model=UserAdminOut,
    status_code=201,
    dependencies=[Depends(require_roles("admin"))],
)
def create_user(payload: UserCreateIn, db: Session = Depends(get_db)) -> UserAdminOut:
    if payload.role not in ALL_ROLES:
        raise HTTPException(status_code=422, detail=f"角色必须是 {'/'.join(ALL_ROLES)}")
    if len(payload.password) < 8:
        raise HTTPException(status_code=422, detail="密码至少 8 位")
    if not payload.username.strip():
        raise HTTPException(status_code=422, detail="用户名不能为空")
    exists = db.scalars(select(User).where(User.username == payload.username.strip())).first()
    if exists is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = User(
        username=payload.username.strip(),
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserAdminOut(
        id=user.id,
        username=user.username,
        role=user.role,
        disabled=user.disabled,
        created_at=user.created_at,
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


def _check_token_budget() -> None:
    """日预算熔断：超限后拒绝新研判，进行中的任务不受影响。"""
    budget = settings.daily_token_budget
    if budget > 0 and llm_ledger.tokens_used_today() >= budget:
        raise HTTPException(
            status_code=429,
            detail=f"今日模型调用预算已耗尽（{budget} tokens），请明天再试或联系管理员调整 DAILY_TOKEN_BUDGET",
        )


def job_to_out(job: AssessmentJob) -> JobOut:
    return JobOut(
        id=job.id,
        assessment_id=job.assessment_id,
        kind=job.kind,
        status=job.status,
        progress_step=job.progress_step,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def _idempotent_replay(
    db: Session,
    key: str,
    response: Response,
    *,
    fingerprint: str | None = None,
) -> AssessmentOut | JobOut | None:
    """重放初始提交；初始任务未结束返回 202，否则返回当前研判 200。"""
    item = find_submission(db, key, fingerprint=fingerprint)
    if item is None:
        return None
    response.status_code = 200
    response.headers["Idempotency-Replayed"] = "true"
    response.headers["Cache-Control"] = "no-store"
    response.headers.update(submission_headers(item.id))
    job = db.scalars(select(AssessmentJob).where(
        AssessmentJob.assessment_id == item.id, AssessmentJob.kind == "create",
    ).order_by(AssessmentJob.created_at, AssessmentJob.id).limit(1)).first()
    if job is not None and job.status in {"queued", "running"}:
        response.status_code = 202
        return job_to_out(job)
    return to_out(item)


@router.get("/assessment-submissions/{key}", response_model=AssessmentOut | JobOut)
def get_submission(key: str, response: Response, db: Session = Depends(get_db)) -> AssessmentOut | JobOut:
    if not IDEMPOTENCY_KEY_RE.fullmatch(key):
        raise HTTPException(status_code=400, detail="无效的提交标识")
    replayed = _idempotent_replay(db, key, response)
    if replayed is None:
        raise HTTPException(status_code=404, detail="暂未找到本次提交，请稍后查询；新建可能产生另一条记录",
                            headers={"Cache-Control": "no-store"})
    return replayed


@router.post("/assessments", response_model=AssessmentOut | JobOut, status_code=201)
@limiter.limit(lambda: f"{get_settings().rate_limit_assessments_per_minute}/minute")
async def create_assessment(
    request: Request,
    description: Annotated[str, Form()] = "",
    followup_answer: Annotated[str, Form()] = "",
    ocr_texts: Annotated[str, Form()] = "",
    files: Annotated[list[UploadFile] | None, File()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    response: Response = None,
    db: Session = Depends(get_db),
    mode: Annotated[Literal["assessment", "classification", "manual"], Form()] = "assessment",
    address: Annotated[str, Form()] = "",
    district: Annotated[str, Form()] = "",
    facility: Annotated[str, Form()] = "",
    scene: Annotated[str, Form()] = "",
    latitude: Annotated[float | None, Form()] = None,
    longitude: Annotated[float | None, Form()] = None,
    coordinate_system: Annotated[Literal["wgs84", "gcj02", "bd09"] | None, Form()] = None,
    data_source: Annotated[Literal["report", "public_case", "simulated"], Form()] = "report",
    event_time: Annotated[str, Form()] = "",
) -> AssessmentOut | JobOut:
    if idempotency_key and not IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key):
        raise HTTPException(status_code=400, detail="Idempotency-Key 需为 8-128 位字母数字或 -_")
    file_list = files or []
    if len(file_list) > settings.max_images:
        raise HTTPException(status_code=400, detail=f"最多上传 {settings.max_images} 张图片")

    image_limit_mb = settings.max_file_bytes // (1024 * 1024)
    staged: list[tuple[UploadFile, bytes]] = []
    for upload in file_list:
        data = await _read_upload_limited(
            upload,
            max_bytes=settings.max_file_bytes,
            detail=f"单张图片不能超过 {image_limit_mb}MB",
        )
        staged.append((upload, data))
    ocr_list = _parse_ocr_texts(ocr_texts)
    try:
        location = LocationData(
            address=address, district=district, facility=facility, scene=scene,
            latitude=latitude, longitude=longitude, coordinate_system=coordinate_system,
            data_source=data_source, event_time=event_time or None,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_context=False)) from exc
    location_fields = {
        "address": location.address, "district": location.district, "facility": location.facility,
        "scene": location.scene, "latitude": location.latitude, "longitude": location.longitude,
        "coordinate_system": location.coordinate_system,
        "event_time": location.event_time.isoformat() if location.event_time else None,
    }
    location_meta = {key: value for key, value in location_fields.items() if value not in (None, "")}
    if location.data_source != "report":
        location_meta["data_source"] = location.data_source
    fingerprint = submission_fingerprint(description, followup_answer, ocr_list, [
        (_safe_filename(upload.filename or "image.jpg", allowed_suffixes=ALLOWED_IMAGE_SUFFIXES,
                        default="image.jpg")[0], data) for upload, data in staged
    ], mode=mode, location=location_meta)
    if idempotency_key:
        replayed = _idempotent_replay(db, idempotency_key, response, fingerprint=fingerprint)
        if replayed is not None:
            return replayed
    _reject_ocr_texts(ocr_list)
    _reject_uploaded_input(description, [data for _, data in staged])
    _reject_text(followup_answer)
    if mode != "manual":
        _check_token_budget()

    assessment = Assessment(
        id=str(uuid4()), description=description,
        record_mode="assessment" if mode == "assessment" else "classification",
        classification_json=None if mode == "assessment" else ClassificationData(
            suggestion_status="manual" if mode == "manual" else "pending",
        ).model_dump_json(),
        address=location.address or None, district=location.district or None,
        facility=location.facility or None, scene=location.scene or None,
        latitude=location.latitude, longitude=location.longitude,
        coordinate_source="manual" if location.latitude is not None else None,
        coordinate_system=location.coordinate_system, data_source=location.data_source,
        event_time=location.event_time,
    )
    upload_root = settings.upload_dir / assessment.id
    written: list[Path] = []
    images: list[ImageInput] = []
    job = None
    try:
        db.add(assessment)
        db.flush()
        if idempotency_key:
            db.add(IdempotencyKey(key=idempotency_key, assessment_id=assessment.id, request_hash=fingerprint))
        upload_root.mkdir(parents=True, exist_ok=False)
        for upload, data in staged:
            original_name, _suffix = _safe_filename(
                upload.filename or "image.jpg",
                allowed_suffixes=ALLOWED_IMAGE_SUFFIXES,
                default="image.jpg",
            )
            target = upload_root / f"{uuid4().hex}_{original_name}"
            written.append(target)
            target.write_bytes(data)
            sniffed_mime = _sniffed_image_mime(data)
            db.add(AssessmentImage(
                assessment_id=assessment.id, filename=original_name, stored_path=str(target),
                mime_type=sniffed_mime, size_bytes=len(data),
            ))
            images.append(ImageInput(filename=original_name, path=target, mime_type=sniffed_mime))
        if settings.workflow_mode == "async":
            job = enqueue_job(db, assessment.id, "create", ocr_texts=ocr_list, answer=followup_answer or None,
                              entry_mode=mode)
        # assessment、图片元数据、幂等键和初始 job 只能一起提交。
        db.commit()
    except Exception as exc:
        db.rollback()
        _cleanup_uncommitted_uploads(upload_root, written)
        if isinstance(exc, IntegrityError) and idempotency_key:
            replayed = _idempotent_replay(db, idempotency_key, response, fingerprint=fingerprint)
            if replayed is not None:
                return replayed
        raise

    response.headers.update(submission_headers(assessment.id))
    if job is not None:
        get_job_runner().wake()
        response.status_code = 202
        return job_to_out(job)

    try:
        # 台账关联：contextvar 经 run_in_threadpool 复制进工作流线程与模型线程池
        ctx_token = llm_ledger.current_assessment_id.set(assessment.id)
        try:
            # 多模型研判是长耗时同步调用，必须移出事件循环，否则阻塞全站请求
            state = await run_in_threadpool(
                run_workflow,
                description=description or "（未填写描述）",
                images=images,
                followup_answer=followup_answer or None,
                followup_used=0,
                ocr_texts=ocr_list,
                **({"entry_mode": mode} if mode != "assessment" else {}),
            )
        finally:
            llm_ledger.current_assessment_id.reset(ctx_token)
    except Exception as exc:
        assessment.status = "failed"
        db.commit()
        raise HTTPException(status_code=502, detail=f"研判服务异常：{exc}",
                            headers=submission_headers(assessment.id)) from exc
    apply_state(assessment, state, db)
    db.commit()
    db.refresh(assessment)
    return to_out(assessment)


def _cleanup_uncommitted_uploads(root: Path, written: list[Path]) -> None:
    """仅删除本次请求记录的文件和空目录；不递归删除任何上传目录。"""
    base = settings.upload_dir.resolve()
    if root.resolve() == base or not root.resolve().is_relative_to(base):
        raise RuntimeError("上传清理目录超出配置范围")
    for path in written:
        if path.resolve().parent != root.resolve():
            raise RuntimeError("上传清理文件超出本次请求目录")
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception("清理未提交上传失败：%s", path.name)
    try:
        root.rmdir()  # 只删除空目录
    except OSError:
        pass


@router.post(
    "/assessments/import",
    response_model=ImportResultOut,
    dependencies=[Depends(require_roles("admin"))],
)
def import_assessments(payload: ImportRowsIn, db: Session = Depends(get_db)) -> ImportResultOut:
    """Bulk-import records with stable external ids; invalid or duplicate rows are reported, not fatal."""
    return ImportResultOut(**import_rows(db, payload.rows))


@router.get("/assessments/{assessment_id}/job", response_model=JobOut)
def get_latest_job(
    assessment_id: str,
    db: Session = Depends(get_db),
) -> JobOut:
    """查询该研判最近一次异步任务的状态（async 模式轮询入口）。"""
    if db.get(Assessment, assessment_id) is None:
        raise HTTPException(status_code=404, detail="研判记录不存在")
    job = db.scalars(
        select(AssessmentJob)
        .where(AssessmentJob.assessment_id == assessment_id)
        .order_by(AssessmentJob.created_at.desc(), AssessmentJob.id.desc())
        .limit(1)
    ).first()
    if job is None:
        raise HTTPException(status_code=404, detail="该研判无异步任务（sync 模式直接返回结果）")
    return job_to_out(job)


@router.get("/assessments", response_model=list[AssessmentOut])
def list_assessments(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[AssessmentOut]:
    if status is not None and status not in ALLOWED_ASSESSMENT_STATUSES:
        raise HTTPException(status_code=422, detail="无效的 status 筛选值")
    limit = max(1, min(limit, 200))
    query = select(Assessment).order_by(Assessment.created_at.desc())
    if status:
        query = query.where(Assessment.status == status)
    query = query.limit(limit).offset(max(0, offset))
    return [to_out(item) for item in db.scalars(query).all()]


@router.get("/assessments/{assessment_id}", response_model=AssessmentOut)
def get_assessment(assessment_id: str, db: Session = Depends(get_db)) -> AssessmentOut:
    item = db.get(Assessment, assessment_id)
    if not item:
        raise HTTPException(status_code=404, detail="研判记录不存在")
    return to_out(item)


@router.post(
    "/assessments/{assessment_id}/followup",
    response_model=AssessmentOut | JobOut,
)
def followup_assessment(
    assessment_id: str,
    payload: FollowupIn,
    response: Response = None,
    db: Session = Depends(get_db),
) -> AssessmentOut | JobOut:
    _reject_text(payload.answer)
    if not payload.answer.strip():
        raise HTTPException(status_code=400, detail="追问回答不能为空")
    _check_token_budget()
    item, reservation = reserve_followup(db, assessment_id, settings.max_followups)
    _reject_text(item.description or "")
    if settings.workflow_mode == "async":
        # 异步模式：从 info 中断点恢复（不重跑视觉模型），完成后回写结果
        thread_id = find_create_thread_id(db, assessment_id)
        job = enqueue_job(
            db,
            assessment_id,
            "followup",
            answer=payload.answer,
            thread_id=thread_id,
            reservation_token=reservation,
        )
        db.commit()
        get_job_runner().wake()
        response.status_code = 202
        return job_to_out(job)
    images = images_from_db(db, assessment_id, kind="original")
    db.commit()  # 在模型调用前提交预留，其他请求立即看到 pending。
    try:
        ctx_token = llm_ledger.current_assessment_id.set(item.id)
        try:
            state = run_workflow(
                description=item.description,
                images=images,
                followup_answer=payload.answer,
                followup_used=item.followup_used,
            )
        finally:
            llm_ledger.current_assessment_id.reset(ctx_token)
        if not finish_followup(db, assessment_id, reservation, state):
            raise HTTPException(status_code=409, detail="追问预留已失效，结果未覆盖")
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        release_followup(db, assessment_id, reservation)
        db.commit()
        raise HTTPException(status_code=502, detail=f"研判服务异常：{exc}") from exc
    db.refresh(item)
    return to_out(item)


@router.post(
    "/assessments/{assessment_id}/confirm",
    response_model=AssessmentOut,
    dependencies=[Depends(require_roles("reviewer", "admin"))],
)
def confirm_assessment(
    assessment_id: str,
    payload: ConfirmIn,
    request: Request,
    response: Response = None,
    db: Session = Depends(get_db),
) -> AssessmentOut:
    item = db.get(Assessment, assessment_id)
    if not item:
        raise HTTPException(status_code=404, detail="研判记录不存在")
    # 审计身份以认证身份为准；无用户体系（none/token）时回退请求体字段（兼容旧客户端）
    user = get_request_user(request)
    reviewer_name = user.username if user else (payload.reviewer or "")
    if not apply_human_review(item, db, payload, reviewer_name, user.id if user else None):
        return to_out(item)
    human_review = parse_json(item.human_review_json) or {}
    if settings.workflow_mode == "async" and item.record_mode != "classification":
        # 人工复核结论回写图线程状态（checkpointer），保持图状态与业务记录一致
        from app.services.langgraph_flow import append_thread_state

        thread_id = find_create_thread_id(db, assessment_id)
        if thread_id:
            append_thread_state(
                thread_id,
                {
                    "confirmed": bool(item.confirmed),
                    "status": item.status,
                    "human_review": human_review,
                    "hazard_category": item.hazard_category,
                    "risk_level": item.risk_level,
                    "conclusion": item.conclusion,
                    "report": parse_json(item.report_json),
                },
            )
    return to_out(item)


@router.post("/assessments/{assessment_id}/rectification", response_model=AssessmentOut)
async def submit_rectification(
    assessment_id: str,
    request: Request,
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
    file_list = files or []
    if len(file_list) > settings.max_images:
        raise HTTPException(status_code=400, detail=f"最多上传 {settings.max_images} 张整改照片")
    for upload in file_list:
        data = await _read_upload_limited(
            upload,
            max_bytes=settings.max_file_bytes,
            detail=f"单张图片不能超过 {settings.max_file_bytes // (1024 * 1024)}MB",
        )
        staged.append((upload, data))
    if not staged:
        raise HTTPException(status_code=400, detail="至少需要上传一张整改后照片")
    _reject_uploaded_input("", [data for _, data in staged])
    _reject_text(note)

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
                mime_type=_sniffed_image_mime(data),
                size_bytes=len(data),
                image_kind="rectification",
            )
        )
    db.flush()
    submit_user = get_request_user(request)
    submit_by = submit_user.username if submit_user else "user"
    submit_rectification_photos(
        item,
        note=note or "提交整改照片并进入人工验证",
        by=submit_by,
    )
    if note:
        item.rectification_note = note
    item.rectified_at = utcnow()
    # AI 前后比对含模型调用（mock 之外最长 60s），同样移出事件循环
    await run_in_threadpool(_run_rectification_compare, item, db)
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
    if _compare_recently_run(item):
        # 同状态窗口内重复比对：复用缓存结果，避免重复调用付费模型
        return to_out(item)
    _run_rectification_compare(item, db)
    db.commit()
    db.refresh(item)
    return to_out(item)


@router.post(
    "/assessments/{assessment_id}/rectification/confirm",
    response_model=AssessmentOut,
    dependencies=[Depends(require_roles("reviewer", "admin"))],
)
def confirm_rectification(
    assessment_id: str,
    payload: RectificationConfirmIn,
    request: Request,
    db: Session = Depends(get_db),
) -> AssessmentOut:
    item = db.get(Assessment, assessment_id)
    if not item:
        raise HTTPException(status_code=404, detail="研判记录不存在")
    target = "verified" if payload.resolved else "rectifying"
    _reject_text(payload.note or "")
    note = payload.note or (
        "人工确认整改完成" if payload.resolved else "人工退回整改"
    )
    confirm_user = get_request_user(request)
    by = confirm_user.username if confirm_user else "user"
    try:
        transition_rectification(item, target, note=note, by=by)
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
    dependencies=[Depends(require_roles("reviewer", "admin"))],
)
def transition_rectification_status(
    assessment_id: str,
    payload: RectificationTransitionIn,
    request: Request,
    db: Session = Depends(get_db),
) -> AssessmentOut:
    item = db.get(Assessment, assessment_id)
    if not item:
        raise HTTPException(status_code=404, detail="研判记录不存在")
    # 审计身份优先认证身份（jwt），无用户体系时回退请求体 by 字段
    trans_user = get_request_user(request)
    by = trans_user.username if trans_user else (payload.by or "user")
    try:
        transition_rectification(
            item,
            payload.to_status,
            note=payload.note,
            by=by,
        )
    except RectificationTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(item)
    return to_out(item)


@router.get("/classification/taxonomy")
def classification_taxonomy() -> dict:
    return {"version": TAXONOMY_VERSION, "categories": CATEGORIES, "tags": TAGS}


@router.post("/assessments/{assessment_id}/classification", response_model=AssessmentOut)
def update_classification(
    assessment_id: str, payload: ClassificationSaveIn, request: Request, db: Session = Depends(get_db),
) -> AssessmentOut:
    item = db.get(Assessment, assessment_id)
    if not item:
        raise HTTPException(status_code=404, detail="记录不存在")
    user = get_request_user(request)
    save_classification(item, db, payload, user.username if user else "", user.id if user else None)
    return to_out(item)


@router.get(
    "/analytics/options",
    response_model=AnalyticsOptionsOut,
    dependencies=[Depends(require_roles("reviewer", "admin"))],
)
def get_analytics_options(db: Session = Depends(get_db)) -> AnalyticsOptionsOut:
    return AnalyticsOptionsOut(**analytics_options(db))


@router.get(
    "/analytics/overview",
    response_model=AnalyticsOverviewOut,
    dependencies=[Depends(require_roles("reviewer", "admin"))],
)
def get_analytics_overview(
    district: str | None = None,
    category: str | None = None,
    facility: str | None = None,
    scene: str | None = None,
    start: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    db: Session = Depends(get_db),
) -> AnalyticsOverviewOut:
    try:
        return AnalyticsOverviewOut(**analytics_overview(
            db, district=district or None, category=category or None, facility=facility or None,
            scene=scene or None, start=start, end=end,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/analytics/benchmarks",
    response_model=BenchmarksOut,
    dependencies=[Depends(require_roles("reviewer", "admin"))],
)
def get_analytics_benchmarks(
    facility: str | None = None,
    scene: str | None = None,
    category: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
) -> BenchmarksOut:
    try:
        return BenchmarksOut(**analytics_benchmarks(
            db, facility=facility or None, scene=scene or None, category=category or None, limit=limit,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/analytics/trend-alerts",
    response_model=TrendReportOut,
    dependencies=[Depends(require_roles("reviewer", "admin"))],
)
def get_trend_alerts(db: Session = Depends(get_db)) -> TrendReportOut:
    return TrendReportOut(**trend_report(db))


@router.post(
    "/analytics/trend-alerts/refresh",
    response_model=TrendReportOut,
    dependencies=[Depends(require_roles("reviewer", "admin"))],
)
def refresh_trend_alerts(db: Session = Depends(get_db)) -> TrendReportOut:
    refresh_alerts(db)
    return TrendReportOut(**trend_report(db))


@router.post(
    "/analytics/trend-alerts/{alert_id}",
    response_model=AlertOut,
    dependencies=[Depends(require_roles("reviewer", "admin"))],
)
def review_trend_alert(
    alert_id: str, payload: AlertReviewIn, request: Request, db: Session = Depends(get_db),
) -> AlertOut:
    item = db.get(TrendAlert, alert_id)
    if item is None:
        raise HTTPException(status_code=404, detail="趋势提示不存在")
    user = get_request_user(request)
    updated = review_alert(
        db, item, payload.status, payload.note, user.username if user else None, user.id if user else None,
    )
    return AlertOut(**alert_out(updated))


def _export_content(item: Assessment) -> str:
    if item.record_mode == "classification":
        data = ClassificationData.model_validate_json(item.classification_json or "{}")
        lines = ["# 隐患分类记录", "", f"- 状态：{item.status}",
                 f"- 分类体系：{data.taxonomy_version}", f"- AI 建议类别：{data.suggested_category or '未知'}",
                 f"- AI 建议标签：{'、'.join(data.suggested_tags) or '无'}",
                 f"- 人工类别：{item.hazard_category or '待录入'}", f"- 人工标签：{'、'.join(data.final_tags) or '无'}",
                 f"- 风险等级：{str(item.risk_level) + ' 级' if item.risk_level else '未分级'}",
                 f"- 人工审核：{'已确认' if item.confirmed else '未确认'}", "", "## 现场描述", item.description,
                 "", "## 人工备注", item.conclusion or "无", "", "## 参考条款（适用性待人工核对）"]
        for entry in parse_json(item.evidence_json) or []:
            lines.append(f"- {entry.get('document', '')} {entry.get('article', '')} / {entry.get('version', '')} "
                         f"/ {entry.get('source', '')}：{entry.get('text', '')}")
            if entry.get("document_id"):
                lines.append(f"  - 版本记录：{entry['document_id']}；"
                             f"内容 SHA256：{entry.get('content_sha256', '未保存')}；"
                             f"行业：{entry.get('industry', '未归类')}；"
                             f"适用范围：{entry.get('applicability', '未注明')}")
        lines.extend(["", *data.warnings])
        return "\n".join(lines)
    effective = effective_result(item)
    report = effective["report"] or {}
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
        effective["conclusion"] or "",
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


@router.get(
    "/knowledge/sources",
    response_model=list[SourceOut],
    dependencies=[Depends(require_roles("admin"))],
)
def list_knowledge_sources(db: Session = Depends(get_db)) -> list[SourceOut]:
    items = db.scalars(select(KnowledgeSource).order_by(
        KnowledgeSource.created_at, KnowledgeSource.id)).all()
    return [SourceOut(**source_out(item)) for item in items]


@router.post(
    "/knowledge/sources",
    response_model=SourceOut,
    status_code=201,
    dependencies=[Depends(require_roles("admin"))],
)
def add_knowledge_source(payload: SourceIn, db: Session = Depends(get_db)) -> SourceOut:
    return SourceOut(**source_out(create_source(db, payload.name, payload.url, payload.industry)))


@router.post(
    "/knowledge/sources/{source_id}/check",
    response_model=SourceOut,
    dependencies=[Depends(require_roles("admin"))],
)
def check_knowledge_source(source_id: str, db: Session = Depends(get_db)) -> SourceOut:
    item = db.get(KnowledgeSource, source_id)
    if item is None:
        raise HTTPException(status_code=404, detail="来源不存在")
    return SourceOut(**source_out(check_source(db, item)))


@router.post(
    "/knowledge/sources/{source_id}/ack",
    response_model=SourceOut,
    dependencies=[Depends(require_roles("admin"))],
)
def acknowledge_knowledge_source(source_id: str, db: Session = Depends(get_db)) -> SourceOut:
    item = db.get(KnowledgeSource, source_id)
    if item is None:
        raise HTTPException(status_code=404, detail="来源不存在")
    return SourceOut(**source_out(acknowledge_source(db, item)))


@router.delete(
    "/knowledge/sources/{source_id}",
    status_code=204,
    dependencies=[Depends(require_roles("admin"))],
)
def remove_knowledge_source(source_id: str, db: Session = Depends(get_db)) -> Response:
    item = db.get(KnowledgeSource, source_id)
    if item is None:
        raise HTTPException(status_code=404, detail="来源不存在")
    delete_source(db, item)
    return Response(status_code=204)


@router.post(
    "/knowledge/documents",
    response_model=DocumentOut,
    status_code=201,
    dependencies=[Depends(require_roles("admin"))],
)
async def upload_knowledge_document(
    title: Annotated[str, Form()] = "未命名文档",
    source: Annotated[str, Form()] = "user-upload",
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    version: Annotated[str, Form()] = "unversioned",
    industry: Annotated[Industry, Form()] = "general",
    applicability: Annotated[str, Form()] = "",
    is_demo: Annotated[bool, Form()] = False,
    supersedes_id: Annotated[str | None, Form()] = None,
) -> DocumentOut:
    try:
        metadata = KnowledgeMetadataIn(title=title, source=source, version=version, industry=industry,
                                       applicability=applicability, is_demo=is_demo, supersedes_id=supersedes_id)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_context=False)) from exc
    data = await _read_upload_limited(
        file,
        max_bytes=settings.max_document_bytes,
        detail=f"文档不能超过 {settings.max_document_bytes // (1024 * 1024)}MB",
    )
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
    doc = create_document_version(db, metadata, text, original_name, suffix)
    _index_document(doc, db)
    return document_out(doc)


def _index_document(doc: KnowledgeDocument, db: Session) -> None:
    try:
        rebuild_knowledge(db=db)
        doc.status = "indexed"
        meta = parse_json(doc.meta_json) or {}
        meta.pop("index_error", None)
        doc.meta_json = json.dumps(meta)
    except Exception:
        doc.status = "index_error"
        doc.meta_json = json.dumps(
            {
                **(parse_json(doc.meta_json) or {}),
                "index_error": "索引重建失败，请管理员重试",
            },
            ensure_ascii=False,
        )
    db.add(doc)
    db.commit()
    db.refresh(doc)


@router.get("/knowledge/documents", response_model=list[DocumentOut])
def list_knowledge_documents(
    db: Session = Depends(get_db), industry: Industry | None = None,
    review_status: Literal["unreviewed", "approved", "rejected", "superseded", "retired"] | None = None,
    series_id: str | None = None,
) -> list[DocumentOut]:
    query = select(KnowledgeDocument)
    if industry:
        query = query.where(KnowledgeDocument.industry == industry)
    if review_status:
        query = query.where(KnowledgeDocument.review_status == review_status)
    if series_id:
        query = query.where(KnowledgeDocument.series_id == series_id)
    return [document_out(doc) for doc in db.scalars(query.order_by(KnowledgeDocument.created_at.desc())).all()]


@router.get("/knowledge/documents/{document_id}")
def get_knowledge_document(document_id: str, db: Session = Depends(get_db)):
    item = db.get(KnowledgeDocument, document_id)
    if not item:
        raise HTTPException(status_code=404, detail="知识文档不存在")
    return {
        **document_out(item).model_dump(),
        "content": (item.content_text or "")[:3000],
        "content_truncated": len(item.content_text or "") > 3000,
    }


@router.get("/knowledge/catalog")
def knowledge_catalog() -> dict:
    return {"industries": [{"value": value, "label": label} for value, label in INDUSTRIES.items()]}


@router.get("/knowledge/documents/{document_id}/articles")
def knowledge_articles(
    document_id: str, offset: int = Query(default=0, ge=0), limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    item = db.get(KnowledgeDocument, document_id)
    if not item:
        raise HTTPException(status_code=404, detail="知识文档不存在")
    records = document_to_records(document_record(item))
    return {"items": records[offset:offset + limit], "total": len(records), "offset": offset, "limit": limit}


@router.get("/knowledge/search")
def search_knowledge(query: str = Query(min_length=1, max_length=2000), industry: Industry | None = None) -> dict:
    _reject_text(query)
    try:
        items = search_approved_knowledge(query, industry=industry)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="知识检索失败，请管理员检查索引后重试") from exc
    notice = "条款适用性仍需结合现场核对" if items else "未找到已审核的有效条款，请核对行业或补充资料"
    return {"items": items, "notice": notice}


@router.post("/knowledge/documents/{document_id}/review", response_model=DocumentOut,
             dependencies=[Depends(require_roles("admin"))])
def review_knowledge_document(
    document_id: str, payload: KnowledgeReviewIn, request: Request, db: Session = Depends(get_db),
) -> DocumentOut:
    item = db.get(KnowledgeDocument, document_id)
    if not item:
        raise HTTPException(status_code=404, detail="知识文档不存在")
    user = get_request_user(request)
    if review_document(db, item, payload, user.username if user else "", user.id if user else None):
        _index_document(item, db)
    return document_out(item)


@router.delete(
    "/knowledge/documents/{document_id}",
    status_code=204,
    dependencies=[Depends(require_roles("admin"))],
)
def delete_knowledge_document(document_id: str, db: Session = Depends(get_db)) -> Response:
    item = db.get(KnowledgeDocument, document_id)
    if not item:
        raise HTTPException(status_code=404, detail="知识文档不存在")
    delete_document_version(db, item)
    try:
        rebuild_knowledge(db=db)
    except Exception:
        # 删除已提交，保持 204 响应稳定；但索引与库状态从此不一致，必须留下日志供运维跟进
        logger.exception("删除知识文档后索引重建失败，知识库与索引可能不一致（document_id=%s）", document_id)
    return Response(status_code=204)


@router.post(
    "/knowledge/rebuild",
    dependencies=[Depends(require_roles("admin"))],
)
def rebuild_knowledge_endpoint(db: Session = Depends(get_db)):
    result = rebuild_knowledge(db=db)
    indexed = {meta["document_id"] for meta in get_rag().metas if meta.get("document_id")}
    if indexed:
        for doc in db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.id.in_(indexed))).all():
            doc.status = "indexed"
            meta = parse_json(doc.meta_json) or {}
            meta.pop("index_error", None)
            doc.meta_json = json.dumps(meta)
        db.commit()
    return {
        "chunks": result["chunks"],
        "records": result["records"],
        "embedding_fallback": result["embedding_fallback"],
    }
