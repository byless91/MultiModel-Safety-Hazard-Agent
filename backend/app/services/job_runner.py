"""进程内研判任务执行器（B3/WP1.1）。

设计要点：
- POST /assessments（async 模式）只写 assessment + job 行即返回 202；
- lifespan 启动的单一 asyncio worker 串行消费任务，工作流在线程池执行，
  不阻塞事件循环（串行是为了让共享的 SQLite checkpointer 连接无并发写）；
- 每完成一个节点通过 progress 回调刷新 job.progress_step；
- 租约与执行代次隔离迟到回写，启动和运行期间均检查故障任务；
- OS 锁限制单实例、单 worker，共享 SQLite checkpoint 不支持多 worker。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Assessment, AssessmentJob
from app.services.assessment_io import apply_state, images_from_db, parse_payload_json
from app.services.worker_lock import WorkerLock

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


def claim_next_job(worker_id: str = "local", *, now: datetime | None = None) -> AssessmentJob | None:
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
        job.worker_id = worker_id
        job.attempt_token = str(uuid.uuid4())
        job.lease_expires_at = (now or datetime.now(UTC)) + timedelta(seconds=get_settings().job_lease_seconds)
        db.commit()
        db.refresh(job)
        return job
    finally:
        db.close()


def recover_stale_jobs(*, now: datetime | None = None, startup: bool = False) -> int:
    """仅恢复 running；startup 必须在取得独占 worker 锁后调用。"""
    settings = get_settings()
    now = now or datetime.now(UTC)
    expired = or_(
        AssessmentJob.lease_expires_at <= now,
        and_(AssessmentJob.lease_expires_at.is_(None),
             AssessmentJob.updated_at < now - timedelta(minutes=settings.job_stale_minutes)),
    )
    db = SessionLocal()
    try:
        query = update(AssessmentJob).where(AssessmentJob.status == "running")
        if not startup:
            query = query.where(expired)
        ids = db.scalars(query.values(
            status="failed", error="任务执行归属丢失或租约超时，已被清扫；未自动重放模型调用",
        ).returning(AssessmentJob.assessment_id)).all()
        if ids:
            db.execute(update(Assessment).where(
                Assessment.id.in_(ids), Assessment.confirmed.is_(False),
                Assessment.status.in_(["pending", "needs_more_info"]),
            ).values(status="failed"))
            db.commit()
            logger.warning("清扫僵尸任务 %d 条", len(ids))
        return len(ids)
    finally:
        db.close()


def _owned_job(job_id: str, attempt_token: str, now: datetime):
    return (
        AssessmentJob.id == job_id, AssessmentJob.status == "running",
        AssessmentJob.attempt_token == attempt_token, AssessmentJob.lease_expires_at > now,
    )


def renew_lease(job_id: str, attempt_token: str, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    with SessionLocal() as db:
        result = db.execute(update(AssessmentJob).where(*_owned_job(job_id, attempt_token, now)).values(
            lease_expires_at=now + timedelta(seconds=get_settings().job_lease_seconds),
        ))
        db.commit()
        return result.rowcount == 1


def _finish_job(job_id: str, attempt_token: str, *, state=None, error: str | None = None) -> bool:
    """取得当前执行代次的写权限后，在同一事务提交 job 和研判结果。"""
    with SessionLocal() as db:
        job = db.scalars(update(AssessmentJob).where(
            *_owned_job(job_id, attempt_token, datetime.now(UTC)),
        ).values(status="failed" if error else "succeeded", error=error).returning(AssessmentJob)).first()
        if job is None:
            return False
        assessment = db.get(Assessment, job.assessment_id)
        if assessment is None or assessment.confirmed or assessment.status not in {"pending", "needs_more_info"}:
            job.status = "failed"
            job.error = "研判状态已变化，拒绝覆盖既有结果"
        elif error:
            assessment.status = "failed"
        else:
            apply_state(assessment, state, db)
            if job.kind == "followup":
                assessment.followup_used += 1
            job.progress_step = str(state.get("status") or "done")
        db.commit()
        return True


def execute_job(job_id: str, attempt_token: str) -> None:
    """在线程池中执行单个任务：运行工作流并回写 assessment 与 job 状态。"""
    db = SessionLocal()
    try:
        job = db.scalars(select(AssessmentJob).where(
            *_owned_job(job_id, attempt_token, datetime.now(UTC)),
        )).first()
        if job is None:
            return
        assessment = db.get(Assessment, job.assessment_id)
        if assessment is None:
            _finish_job(job_id, attempt_token, error=f"assessment {job.assessment_id} 不存在")
            return
        images = images_from_db(db, assessment.id, kind="original")
        # 不在模型网络调用期间持有读事务或 ORM 身份缓存。
        db.expunge_all()
        db.close()

        def progress(step: str) -> None:
            with SessionLocal() as progress_db:
                result = progress_db.execute(update(AssessmentJob).where(
                    *_owned_job(job_id, attempt_token, datetime.now(UTC)),
                ).values(progress_step=step))
                progress_db.commit()
                if result.rowcount != 1:
                    raise RuntimeError("任务执行代次已失效，停止后续节点")

        # 台账关联：本线程及下游模型线程池（copy_context）都携带 assessment_id
        from app.services import llm_ledger

        ctx_token = llm_ledger.current_assessment_id.set(assessment.id)
        try:
            if job.kind == "create":
                from app.services.workflow import run_workflow

                payload = parse_payload_json(job.payload_json)
                state = run_workflow(
                    description=assessment.description or "（未填写描述）",
                    images=images,
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
                        images=images,
                        followup_answer=job.answer,
                        followup_used=assessment.followup_used,
                        progress=progress,
                    )
            _finish_job(job_id, attempt_token, state=state)
        except Exception as exc:
            logger.exception("研判任务执行失败 job_id=%s", job_id)
            _finish_job(job_id, attempt_token, error=str(exc)[:500])
        finally:
            llm_ledger.current_assessment_id.reset(ctx_token)
    finally:
        db.close()


class JobRunner:
    """asyncio 事件循环内的串行任务泵：认领 → 线程池执行 → 继续认领。"""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._stopped = False
        self._monitor: asyncio.Task | None = None
        self._execution: asyncio.Task | None = None
        self._active: AssessmentJob | None = None
        self._lock: WorkerLock | None = None
        self._worker_id = ""

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        if self._lock is not None:
            raise RuntimeError("上次 worker 的模型调用仍未退出")
        settings = get_settings()
        self._lock = WorkerLock(settings.langgraph_checkpoint_path.with_suffix(".worker.lock"))
        self._worker_id = str(uuid.uuid4())
        self._wake = asyncio.Event()  # lifespan 重启时绑定新的事件循环
        self._stopped = False
        try:
            recovered = await asyncio.to_thread(recover_stale_jobs, startup=True)
        except BaseException:
            self._release_lock()
            raise
        if recovered:
            logger.warning("启动时清扫僵尸任务 %d 条", recovered)
        self._task = asyncio.create_task(self._loop(), name="assessment-job-runner")
        self._monitor = asyncio.create_task(self._monitor_loop(), name="assessment-job-monitor")
        logger.info("研判任务 worker 已启动（async 模式）")

    async def stop(self) -> None:
        self._stopped = True
        self._wake.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None
        if self._monitor is not None:
            self._monitor.cancel()
            await asyncio.gather(self._monitor, return_exceptions=True)
            self._monitor = None
        if self._active is not None:
            await asyncio.to_thread(
                _finish_job, self._active.id, self._active.attempt_token, error="worker 停止，未重放调用",
            )
        if self._execution is not None and not self._execution.done():
            # 底层线程不可取消；退出前继续持有 checkpoint 锁，阻止新 worker 并发写。
            self._execution.add_done_callback(lambda _: self._release_lock())
        else:
            self._release_lock()

    def _release_lock(self) -> None:
        if self._lock is not None:
            self._lock.release()
            self._lock = None

    async def _monitor_loop(self) -> None:
        while True:
            await asyncio.sleep(min(get_settings().job_monitor_seconds, get_settings().job_lease_seconds / 3))
            try:
                job = self._active
                if job is not None:
                    await asyncio.to_thread(renew_lease, job.id, job.attempt_token)
                await asyncio.to_thread(recover_stale_jobs)
            except Exception:
                logger.exception("任务租约监测失败，下个周期重试")

    def wake(self) -> None:
        """新任务入队后由 API 调用，立即唤醒轮询。"""
        self._wake.set()

    async def _loop(self) -> None:
        from fastapi.concurrency import run_in_threadpool

        while not self._stopped:
            try:
                job = await run_in_threadpool(claim_next_job, self._worker_id)
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
                self._active = job
                self._execution = asyncio.create_task(asyncio.to_thread(execute_job, job.id, job.attempt_token))
                await asyncio.shield(self._execution)
                self._active = None
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
