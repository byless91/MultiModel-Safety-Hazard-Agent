"""B0/WP0.1：性能止血——事件循环响应性与 SQLite 并发防护的回归测试。"""

import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import routes as routes_module
from app.core.db import engine
from app.main import app


def test_sqlite_wal_and_busy_timeout_enabled():
    if not str(engine.url).startswith("sqlite"):
        pytest.skip("非 SQLite 后端")
    with engine.connect() as conn:
        journal = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        timeout = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
    assert str(journal).lower() == "wal", "SQLite 未启用 WAL，并发读写会互相阻塞"
    assert int(timeout) >= 5000, "SQLite 未设置 busy_timeout，瞬时锁冲突会直接报错"


def test_health_stays_responsive_while_workflow_runs(monkeypatch):
    """研判进行中 /health 必须及时响应；若 run_workflow 回到事件循环内同步执行，本测试失败。"""

    def slow_workflow(
        *, description, images, followup_answer=None, followup_used=0, ocr_texts=None
    ):
        time.sleep(1.2)  # 模拟多模型调用耗时：应只阻塞工作线程，不阻塞事件循环
        return {"status": "completed", "evidence": []}

    monkeypatch.setattr(routes_module, "run_workflow", slow_workflow)

    with TestClient(app) as client:
        client.get("/api/v1/health")  # 触发 startup（init_db / 预热 Provider 与 RAG）

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            post = asyncio.create_task(
                ac.post("/api/v1/assessments", data={"description": "楼道堆放纸箱杂物"})
            )
            await asyncio.sleep(0.4)  # 等待请求进入 workflow 阶段
            started = time.monotonic()
            response = await asyncio.wait_for(ac.get("/api/v1/health"), timeout=1.0)
            elapsed = time.monotonic() - started
            assert response.status_code == 200
            assert elapsed < 1.0, f"/health 被研判请求阻塞了 {elapsed:.2f}s"
            result = await post
            assert result.status_code == 201

    asyncio.run(scenario())
