import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    rectified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
