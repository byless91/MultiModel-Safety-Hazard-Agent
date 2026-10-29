"""LLM 调用台账（B5/WP3.2）：每次真实模型调用（含失败）落库，成本可审计。

上下文经 contextvars 传递：assessment_id 由 API/worker 在业务线程绑定，
purpose 由各调用方（analyze/refine/compare/embed）绑定；
analyzer 的线程池用 copy_context 把上下文带进工作线程。
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, select

from app.core.db import SessionLocal
from app.core.logging import get_request_id
from app.models import LLMCall

logger = logging.getLogger("safety_hazard.llm_ledger")

current_assessment_id: ContextVar[str | None] = ContextVar(
    "llm_assessment_id", default=None
)
current_purpose: ContextVar[str] = ContextVar("llm_purpose", default="analyze")


def record_call(
    *,
    provider: str,
    model: str,
    status: str,
    latency_ms: float,
    purpose: str | None = None,
    prompt_version: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    retry_count: int = 0,
    error_type: str = "",
    parse_failed: bool = False,
    assessment_id: str | None = None,
) -> str | None:
    """写入一条台账；失败只告警，绝不阻断业务调用。返回行 id（供 parse_failed 回填）。"""
    try:
        db = SessionLocal()
        try:
            row = LLMCall(
                assessment_id=assessment_id or current_assessment_id.get(),
                request_id=get_request_id(),
                provider=provider,
                model=model,
                purpose=purpose or current_purpose.get(),
                prompt_version=prompt_version,
                status=status,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                retry_count=retry_count,
                error_type=error_type[:120],
                parse_failed=parse_failed,
                latency_ms=round(latency_ms, 1),
            )
            db.add(row)
            db.commit()
            return row.id
        finally:
            db.close()
    except Exception:
        logger.warning("台账写入失败（不影响业务）", exc_info=True)
        return None


def mark_parse_failed(row_id: str | None) -> None:
    """模型输出 JSON 解析失败：把台账行标记为 parse_failed。"""
    if not row_id:
        return
    try:
        db = SessionLocal()
        try:
            row = db.get(LLMCall, row_id)
            if row is not None:
                row.parse_failed = True
                row.status = "parse_failed"
                db.commit()
        finally:
            db.close()
    except Exception:
        logger.warning("台账 parse_failed 回填失败", exc_info=True)


def tokens_used_today() -> int:
    """今日（UTC）已消耗 token 总量，用于预算熔断。"""
    db = SessionLocal()
    try:
        since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        total = db.scalar(
            select(func.coalesce(func.sum(LLMCall.tokens_in + LLMCall.tokens_out), 0)).where(
                LLMCall.created_at >= since
            )
        )
        return int(total or 0)
    finally:
        db.close()


def usage_summary(days: int = 7) -> list[dict[str, Any]]:
    """按 天×provider×purpose 聚合的用量视图（admin 接口用）。"""
    db = SessionLocal()
    try:
        since = datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        from datetime import timedelta

        since = since - timedelta(days=max(0, days - 1))
        rows = db.execute(
            select(
                func.date(LLMCall.created_at).label("day"),
                LLMCall.provider,
                LLMCall.purpose,
                func.count(LLMCall.id).label("calls"),
                func.sum(
                    case((LLMCall.status == "success", 1), else_=0)
                ).label("success"),
                func.sum(
                    case((LLMCall.status == "failed", 1), else_=0)
                ).label("failed"),
                func.sum(LLMCall.tokens_in).label("tokens_in"),
                func.sum(LLMCall.tokens_out).label("tokens_out"),
                func.avg(LLMCall.latency_ms).label("avg_latency_ms"),
            )
            .where(LLMCall.created_at >= since)
            .group_by("day", LLMCall.provider, LLMCall.purpose)
            .order_by(func.date(LLMCall.created_at).desc())
        ).all()
        return [
            {
                "day": str(row.day),
                "provider": row.provider,
                "purpose": row.purpose,
                "calls": int(row.calls or 0),
                "success": int(row.success or 0),
                "failed": int(row.failed or 0),
                "tokens_in": int(row.tokens_in or 0),
                "tokens_out": int(row.tokens_out or 0),
                "avg_latency_ms": round(float(row.avg_latency_ms or 0), 1),
            }
            for row in rows
        ]
    finally:
        db.close()
