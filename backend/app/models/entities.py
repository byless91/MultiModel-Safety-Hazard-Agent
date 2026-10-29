import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (
        Index("uq_assessments_source_ref", "data_source", "source_ref", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    record_mode: Mapped[str] = mapped_column(String(24), default="assessment", server_default="assessment")
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    district: Mapped[str | None] = mapped_column(String(128), nullable=True)
    facility: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scene: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    coordinate_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    coordinate_system: Mapped[str | None] = mapped_column(String(16), nullable=True)
    data_source: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    import_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    classification_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    scene_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    hazard_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    risk_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    followup_questions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    followup_used: Mapped[int] = mapped_column(Integer, default=0)
    followup_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confirmed: Mapped[bool] = mapped_column(default=False)
    rectification_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rectification_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    rectification_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rectification_analysis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    rectification_meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    rectified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_reasons_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_review_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_judge_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ensemble_judge_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    multi_model_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    disagreement_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    # B4/WP2.2：复核审计身份（jwt 模式取认证身份，不可由客户端伪造）
    confirmed_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    confirmed_by_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    images: Mapped[list["AssessmentImage"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )


class AssessmentImage(Base):
    __tablename__ = "assessment_images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    image_kind: Mapped[str] = mapped_column(String(32), default="original")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    assessment: Mapped[Assessment] = relationship(back_populates="images")


class AssessmentJob(Base):
    """异步研判任务（B3/WP1.1）：POST 立即返回 202，worker 串行消费。"""

    __tablename__ = "assessment_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), default="create")  # create | followup
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)  # followup 的补充回答
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # create 的 ocr_texts 等
    thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    progress_step: Mapped[str] = mapped_column(String(32), default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attempt_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class IdempotencyKey(Base):
    """POST /assessments 的幂等键（B3/WP1.3）：同 key 重复请求返回首次结果。"""

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(36), index=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    """登录用户（B4/WP2.1）。密码只存 bcrypt 哈希。"""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default="inspector")  # admin|inspector|reviewer
    disabled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class LLMCall(Base):
    """LLM 调用台账（B5/WP3.2）：真实模型调用（含失败）逐条落库。"""

    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    assessment_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(16), default="analyze")  # analyze|refine|compare|embed
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="success")  # success|failed|parse_failed
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_type: Mapped[str] = mapped_column(String(128), default="")
    parse_failed: Mapped[bool] = mapped_column(default=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        Index("uq_knowledge_series_version", "series_id", "version", unique=True),
        Index("uq_knowledge_active_series", "series_id", unique=True,
              sqlite_where=text("review_status = 'approved'"), postgresql_where=text("review_status = 'approved'")),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255))
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="parsed")
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    industry: Mapped[str] = mapped_column(String(24), default="general", server_default="general")
    applicability: Mapped[str] = mapped_column(Text, default="", server_default="")
    review_status: Mapped[str] = mapped_column(String(24), default="unreviewed", server_default="unreviewed")
    series_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    supersedes_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeSource(Base):
    """Authoritative source watched for version changes; never publishes content itself."""

    __tablename__ = "knowledge_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text)
    industry: Mapped[str] = mapped_column(String(24), default="general", server_default="general")
    last_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acknowledged_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    change_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TrendAlert(Base):
    """One explainable rule hit per scope and month; human decisions are retained."""

    __tablename__ = "trend_alerts"
    __table_args__ = (
        Index("uq_trend_alert_scope_month", "rule_version", "scope_type", "scope_value", "month", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    rule_version: Mapped[str] = mapped_column(String(32))
    scope_type: Mapped[str] = mapped_column(String(24), default="category")
    scope_value: Mapped[str] = mapped_column(String(128), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    observed: Mapped[int] = mapped_column(Integer)
    baseline: Mapped[float] = mapped_column(Float)
    ratio_threshold: Mapped[float] = mapped_column(Float)
    sample_size: Mapped[int] = mapped_column(Integer)
    explanation: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="open", server_default="open")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class KnowledgePackImport(Base):
    """One verified knowledge-pack import; the latest row is the local sync marker."""

    __tablename__ = "knowledge_pack_imports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    pack_version: Mapped[str] = mapped_column(String(32))
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    imported: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    superseded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    imported_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
