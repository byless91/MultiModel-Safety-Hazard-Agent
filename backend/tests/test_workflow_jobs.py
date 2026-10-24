"""B3/WP1.1+WP1.2：异步研判任务化、断点恢复与追问不重跑视觉模型。

async 模式合同：POST /assessments 返回 202 + JobOut；worker 串行消费并
逐步更新 progress_step；followup 走 interrupt/resume，不重新调用视觉模型。
"""

import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 48

NEEDS_INFO_CASE = "现场有异常"
COMPLETED_CASE = "小区楼道堆放纸箱杂物，堵塞疏散通道，通行明显受阻"


def _enable_async(monkeypatch):
    monkeypatch.setattr(get_settings(), "workflow_mode", "async")


def _wait_job(client: TestClient, assessment_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/v1/assessments/{assessment_id}/job")
        if resp.status_code == 200:
            job = resp.json()
            if job["status"] in ("succeeded", "failed"):
                return job
        time.sleep(0.2)
    pytest.fail(f"任务超时未完成 assessment_id={assessment_id}")


def test_async_submit_returns_202_then_job_completes(monkeypatch):
    _enable_async(monkeypatch)
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/assessments",
            data={"description": COMPLETED_CASE},
            files=[("files", ("scene.png", FAKE_PNG, "image/png"))],
        )
        assert created.status_code == 202, created.text
        job = created.json()
        assert job["kind"] == "create"
        assert job["status"] in ("queued", "running", "succeeded")
        assert job["assessment_id"]

        final = _wait_job(client, job["assessment_id"])
        assert final["status"] == "succeeded", final.get("error")

        assessment = client.get(f"/api/v1/assessments/{job['assessment_id']}").json()
        assert assessment["status"] in ("completed", "awaiting_human_review")
        assert assessment["hazard_category"]
        assert assessment["findings"]
        assert assessment["images"][0]["mime_type"] == "image/png"


def test_async_three_jobs_all_complete(monkeypatch):
    _enable_async(monkeypatch)
    cases = [
        "灭火器压力表指针在红区",
        "小区人行道井盖轻微破损",
        "林区有游客在防火期野外用火",
    ]
    with TestClient(app) as client:
        ids = []
        for description in cases:
            created = client.post("/api/v1/assessments", data={"description": description})
            assert created.status_code == 202
            ids.append(created.json()["assessment_id"])
        for assessment_id in ids:
            job = _wait_job(client, assessment_id)
            assert job["status"] == "succeeded", job.get("error")
            item = client.get(f"/api/v1/assessments/{assessment_id}").json()
            assert item["hazard_category"]


def test_job_endpoint_404_in_sync_mode():
    """sync 模式（默认）没有任务行，job 查询接口 404。"""
    with TestClient(app) as client:
        created = client.post("/api/v1/assessments", data={"description": COMPLETED_CASE})
        assert created.status_code == 201
        response = client.get(f"/api/v1/assessments/{created.json()['id']}/job")
    assert response.status_code == 404


def test_recover_stale_jobs_marks_timeout_failed():
    from app.core.db import SessionLocal
    from app.models import Assessment, AssessmentJob
    from app.services.job_runner import recover_stale_jobs

    db = SessionLocal()
    try:
        assessment = Assessment(description="僵尸任务关联研判")
        db.add(assessment)
        db.flush()
        stale = AssessmentJob(
            assessment_id=assessment.id,
            kind="create",
            status="running",
            progress_step="analyze",
            updated_at=datetime.now(UTC) - timedelta(minutes=30),
        )
        db.add(stale)
        db.commit()
        stale_id = stale.id
    finally:
        db.close()

    recovered = recover_stale_jobs()
    assert recovered >= 1

    db = SessionLocal()
    try:
        job = db.get(AssessmentJob, stale_id)
        assert job.status == "failed"
        assert "清扫" in (job.error or "")
    finally:
        db.close()


def test_resume_does_not_re_analyze_vision():
    """WP1.2 验收：追问恢复后视觉模型 analyze 调用次数不增加。"""
    from app.services import langgraph_flow
    from app.services.providers.mock import MockProvider
    from app.services.rag import get_rag

    class CountingProvider(MockProvider):
        analyze_calls = 0

        def analyze(self, images, text, **kwargs):
            type(self).analyze_calls += 1
            return super().analyze(images, text, **kwargs)

    provider = CountingProvider()
    thread_id = "test-resume-no-reanalyze-1"

    state1 = langgraph_flow.run_langgraph(
        NEEDS_INFO_CASE,
        [],
        followup_used=0,
        settings=get_settings(),
        rag=get_rag(),
        providers=[provider],
        use_checkpointer=True,
        thread_id=thread_id,
    )
    assert state1["status"] == "needs_more_info"
    assert state1["followup_questions"]
    assert CountingProvider.analyze_calls == 1

    state2 = langgraph_flow.resume_workflow(
        thread_id, "楼道堆放了大量纸箱，影响疏散通道通行"
    )
    assert state2 is not None
    assert state2["status"] in ("completed", "awaiting_human_review")
    assert "补充信息" in state2["description"]
    # 断点恢复：analyze 节点不重新执行
    assert CountingProvider.analyze_calls == 1


def test_checkpoint_survives_saver_restart():
    """模拟进程重启（重建 saver 连接与图实例）后 thread 状态仍可恢复。"""
    from app.core.config import get_settings
    from app.services import langgraph_flow
    from app.services.providers.mock import MockProvider
    from app.services.rag import get_rag

    thread_id = "test-restart-recovery-1"
    langgraph_flow.run_langgraph(
        NEEDS_INFO_CASE,
        [],
        followup_used=0,
        settings=get_settings(),
        rag=get_rag(),
        providers=[MockProvider()],
        use_checkpointer=True,
        thread_id=thread_id,
    )
    # 模拟重启：丢弃 saver 与已编译图（checkpoint 文件仍在磁盘上）
    langgraph_flow._saver = None
    langgraph_flow._graphs.clear()

    state = langgraph_flow.resume_workflow(thread_id, "补充：现场为楼道堆放纸箱")
    assert state is not None, "重启后无法从 checkpoint 恢复线程"
    assert state["status"] in ("completed", "awaiting_human_review")


def test_async_followup_full_flow(monkeypatch):
    """async 模式追问全链路：needs_more_info → followup 任务 → 恢复完成。"""
    _enable_async(monkeypatch)
    with TestClient(app) as client:
        created = client.post("/api/v1/assessments", data={"description": NEEDS_INFO_CASE})
        assert created.status_code == 202
        assessment_id = created.json()["assessment_id"]
        first = _wait_job(client, assessment_id)
        assert first["status"] == "succeeded"
        assert first["progress_step"] == "needs_more_info"

        item = client.get(f"/api/v1/assessments/{assessment_id}").json()
        assert item["status"] == "needs_more_info"
        assert item["followup_questions"]

        followup = client.post(
            f"/api/v1/assessments/{assessment_id}/followup",
            json={"answer": "楼道堆放了大量纸箱，影响疏散通道通行"},
        )
        assert followup.status_code == 202, followup.text
        assert followup.json()["kind"] == "followup"

        second = _wait_job(client, assessment_id)
        assert second["status"] == "succeeded", second.get("error")

        item = client.get(f"/api/v1/assessments/{assessment_id}").json()
        assert item["followup_used"] == 1
        assert item["status"] in ("completed", "awaiting_human_review")


def test_async_second_followup_falls_back_to_full_rerun(monkeypatch):
    """线程已完成后再次追问：无挂起中断，worker 回退全量重跑。"""
    _enable_async(monkeypatch)
    with TestClient(app) as client:
        created = client.post("/api/v1/assessments", data={"description": COMPLETED_CASE})
        assessment_id = created.json()["assessment_id"]
        _wait_job(client, assessment_id)

        followup = client.post(
            f"/api/v1/assessments/{assessment_id}/followup",
            json={"answer": "补充描述：现场还有电动车飞线充电"},
        )
        assert followup.status_code == 202
        second = _wait_job(client, assessment_id)
        assert second["status"] == "succeeded", second.get("error")

        item = client.get(f"/api/v1/assessments/{assessment_id}").json()
        assert item["followup_used"] == 1


def test_async_confirm_writes_back_to_checkpoint(monkeypatch):
    _enable_async(monkeypatch)
    with TestClient(app) as client:
        created = client.post("/api/v1/assessments", data={"description": COMPLETED_CASE})
        assessment_id = created.json()["assessment_id"]
        _wait_job(client, assessment_id)

        confirmed = client.post(
            f"/api/v1/assessments/{assessment_id}/confirm",
            json={"confirmed": True, "reviewer": "张复核员"},
        )
        assert confirmed.status_code == 200

        from app.core.db import SessionLocal
        from app.services.job_runner import find_create_thread_id
        from app.services.langgraph_flow import get_graph

        db = SessionLocal()
        try:
            thread_id = find_create_thread_id(db, assessment_id)
        finally:
            db.close()
        assert thread_id
        snapshot = get_graph(use_checkpointer=True).get_state(
            {"configurable": {"thread_id": thread_id}}
        )
        assert snapshot.values.get("confirmed") is True
        assert snapshot.values.get("status") == "confirmed"
