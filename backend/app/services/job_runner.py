"""进程内研判任务执行器（B3/WP1.1）。

设计要点：
- POST /assessments（async 模式）只写 assessment + job 行即返回 202；
- lifespan 启动的单一 asyncio worker 串行消费任务，工作流在线程池执行，
  不阻塞事件循环（串行是为了让共享的 SQLite checkpointer 连接无并发写）；
- 每完成一个节点通过 progress 回调刷新 job.progress_step；
- 启动时清扫僵尸任务（queued/running 超时 → failed），进程崩溃后可恢复；
- 多 worker 部署需改为原子认领（UPDATE ... RETURNING）+ Postgres checkpointer，
  见计划书 B5。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Assessment, AssessmentJob
from app.services.assessment_io import apply_state, images_from_db, parse_payload_json

logger = logging.getLogger("safety_hazard.jobs")


def enqueue_job(
    db,
    assessment_id: str,
    kind: str,
    *,
    answer: str | None = None,
    ocr_texts: list[str] | None = None,
    thread_id: str | None = None,
) -> AssessmentJob:
    job = AssessmentJob(
        assessment_id=assessment_id,
        kind=kind,
        answer=answer,
        payload_json=json.dumps({"ocr_texts": ocr_texts or []}, ensure_ascii=False)
        if kind == "create"
        else None,
        thread_id=thread_id,
        status="queued",
        progress_step="queued",
    )
    db.add(job)
    db.flush()
    if kind == "create" and thread_id is None:
        # async 模式以 create 任务的 id 作为 LangGraph thread_id，followup 据此恢复
        job.thread_id = job.id
    return job


def find_create_thread_id(db, assessment_id: str) -> str | None:
    job = db.scalars(
        select(AssessmentJob)
        .where(
            AssessmentJob.assessment_id == assessment_id,
            AssessmentJob.kind == "create",
        )
        .order_by(AssessmentJob.created_at)
        .limit(1)
    ).first()
    return job.thread_id if job else None


def claim_next_job() -> AssessmentJob | None:
    """认领下一个排队任务（单 worker 串行，无竞态）。"""
    db = SessionLocal()
    try:
        job = db.scalars(
            select(AssessmentJob)
            .where(AssessmentJob.status == "queued")
            .order_by(AssessmentJob.created_at, AssessmentJob.id)
            .limit(1)
        ).first()
        if job is None:
            return None
        job.status = "running"
        db.commit()
        db.refresh(job)
        return job
    finally:
        db.close()


def recover_stale_jobs() -> int:
    """启动清扫：上次进程崩溃遗留的 queued/running 任务标记失败。"""
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.job_stale_minutes)
    db = SessionLocal()
    try:
        jobs = db.scalars(
            select(AssessmentJob).where(AssessmentJob.status.in_(["queued", "running"]))
        ).all()
        recovered = 0
        for job in jobs:
            updated = job.updated_at or job.created_at
            if updated is None or _as_utc(updated) < cutoff:
                job.status = "failed"
                job.error = "任务超时未完成（进程重启或 worker 异常），已被清扫"
                assessment = db.get(Assessment, job.assessment_id)
                if assessment is not None and assessment.status == "pending":
                    assessment.status = "failed"
                recovered += 1
        if recovered:
            db.commit()
            logger.warning("清扫僵尸任务 %d 条", recovered)
        return recovered
    finally:
        db.close()


def _as_utc(value: datetime) -> datetime:
    """SQLite 读回的时间戳无 tzinfo（存储的都是 UTC），统一按 UTC 解释。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def execute_job(job_id: str) -> None:
    """在线程池中执行单个任务：运行工作流并回写 assessment 与 job 状态。"""
    db = SessionLocal()
    try:
        job = db.get(AssessmentJob, job_id)
        if job is None:
            return
        assessment = db.get(Assessment, job.assessment_id)
        if assessment is None:
            job.status = "failed"
            job.error = f"assessment {job.assessment_id} 不存在"
            db.commit()
            return

        def progress(step: str) -> None:
            job.progress_step = step
            db.commit()

        try:
            if job.kind == "create":
                from app.services.workflow import run_workflow

                payload = parse_payload_json(job.payload_json)
                state = run_workflow(
                    description=assessment.description or "（未填写描述）",
                    images=images_from_db(db, assessment.id, kind="original"),
                    followup_answer=None,
                    followup_used=assessment.followup_used,
                    ocr_texts=payload.get("ocr_texts") or [],
                    progress=progress,
                    thread_id=job.thread_id,
                    use_checkpointer=True,
                )
            else:
                from app.services.langgraph_flow import resume_workflow

                state = resume_workflow(
                    thread_id=job.thread_id or "",
                    answer=job.answer or "",
                    progress=progress,
                )
                if state is None:
                    # 线程已无挂起中断（例如完成后再次追问）：回退为全量重跑
                    from app.services.workflow import run_workflow

                    state = run_workflow(
                        description=assessment.description,
                        images=images_from_db(db, assessment.id, kind="original"),
                        followup_answer=job.answer,
                        followup_used=assessment.followup_used,
                        progress=progress,
                    )
            apply_state(assessment, state, db)
            if job.kind == "followup":
                assessment.followup_used += 1
            job.status = "succeeded"
            job.progress_step = str(state.get("status") or "done")
            job.error = None
        except Exception as exc:
            logger.exception("研判任务执行失败 job_id=%s", job_id)
            job.status = "failed"
            job.error = str(exc)[:500]
            assessment.status = "failed"
        db.commit()
    finally:
        db.close()


class JobRunner:
    """asyncio 事件循环内的串行任务泵：认领 → 线程池执行 → 继续认领。"""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._stopped = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stopped = False
        recovered = await asyncio.to_thread(recover_stale_jobs)
        if recovered:
            logger.warning("启动时清扫僵尸任务 %d 条", recovered)
        self._task = asyncio.create_task(self._loop(), name="assessment-job-runner")
        logger.info("研判任务 worker 已启动（async 模式）")

    async def stop(self) -> None:
        self._stopped = True
        self._wake.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None

    def wake(self) -> None:
        """新任务入队后由 API 调用，立即唤醒轮询。"""
        self._wake.set()

    async def _loop(self) -> None:
        from fastapi.concurrency import run_in_threadpool

        while not self._stopped:
            try:
                job = await run_in_threadpool(claim_next_job)
                if job is None:
                    self._wake.clear()
                    try:
                        await asyncio.wait_for(self._wake.wait(), timeout=1.0)
                    except TimeoutError:
                        pass
                    continue
                logger.info(
                    "开始执行研判任务 job_id=%s kind=%s assessment_id=%s",
                    job.id,
                    job.kind,
                    job.assessment_id,
                )
                await run_in_threadpool(execute_job, job.id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("任务泵异常，1 秒后继续")
                await asyncio.sleep(1.0)


_runner: JobRunner | None = None


def get_job_runner() -> JobRunner:
    global _runner
    if _runner is None:
        _runner = JobRunner()
    return _runner


ProgressCallback = Callable[[str], None]
