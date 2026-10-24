import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    scene_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    hazard_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    risk_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    followup_questions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    followup_used: Mapped[int] = mapped_column(Integer, default=0)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class IdempotencyKey(Base):
    """POST /assessments 的幂等键（B3/WP1.3）：同 key 重复请求返回首次结果。"""

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255))
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="parsed")
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
