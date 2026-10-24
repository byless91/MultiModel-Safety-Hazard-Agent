"""B3/WP1.3：幂等键与整改比对去重。

- POST /assessments 携带 Idempotency-Key：同 key 重复请求返回首次结果，
  不重复创建研判（也就不重复调用模型）；
- /rectification/compare：同整改状态 + 时间窗口内的重复比对复用缓存。
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app

FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 48


def test_sync_same_key_returns_first_result():
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/assessments",
            data={"description": "小区楼道堆放纸箱杂物，堵塞疏散通道"},
            headers={"Idempotency-Key": "idem-key-0001"},
        )
        assert first.status_code == 201
        first_id = first.json()["id"]

        replay = client.post(
            "/api/v1/assessments",
            data={"description": "小区楼道堆放纸箱杂物，堵塞疏散通道"},
            headers={"Idempotency-Key": "idem-key-0001"},
        )
        assert replay.status_code == 200
        assert replay.headers.get("Idempotency-Replayed") == "true"
        assert replay.json()["id"] == first_id

        items = client.get("/api/v1/assessments").json()
        same = [item for item in items if item["id"] == first_id]
        assert len(same) == 1, "同 key 重复请求不得创建新研判"


def test_invalid_idempotency_key_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/assessments",
            data={"description": "楼道堆物"},
            headers={"Idempotency-Key": "bad key!!"},
        )
    assert response.status_code == 400


def test_expired_key_allows_new_request():
    from app.core.db import SessionLocal
    from app.models import IdempotencyKey

    with TestClient(app) as client:
        first = client.post(
            "/api/v1/assessments",
            data={"description": "灭火器压力异常"},
            headers={"Idempotency-Key": "idem-key-expired"},
        )
        assert first.status_code == 201

        # 把键标记为 25 小时前创建（超过 24h TTL）
        db = SessionLocal()
        try:
            row = db.get(IdempotencyKey, "idem-key-expired")
            row.created_at = datetime.now(UTC) - timedelta(hours=25)
            db.commit()
        finally:
            db.close()

        second = client.post(
            "/api/v1/assessments",
            data={"description": "灭火器压力异常"},
            headers={"Idempotency-Key": "idem-key-expired"},
        )
        assert second.status_code == 201, "过期键应放行新请求"
        assert second.json()["id"] != first.json()["id"]


def test_async_replay_returns_job_while_pending(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "workflow_mode", "async")
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/assessments",
            data={"description": "现场有异常"},
            headers={"Idempotency-Key": "idem-key-async-1"},
        )
        assert first.status_code == 202
        first_body = first.json()

        replay = client.post(
            "/api/v1/assessments",
            data={"description": "现场有异常"},
            headers={"Idempotency-Key": "idem-key-async-1"},
        )
        # 任务未完成时重放返回同一任务（202）；完成后重放返回 assessment（200）
        assert replay.status_code in (200, 202)
        if replay.status_code == 202:
            assert replay.json()["id"] == first_body["id"]
        else:
            assert replay.json()["id"] == first_body["assessment_id"]


def _counting_provider(monkeypatch):
    from app.services.providers.mock import MockProvider

    class CountingCompare(MockProvider):
        compare_calls = 0

        def compare(self, originals, rectifications, note=""):
            type(self).compare_calls += 1
            return super().compare(originals, rectifications, note)

    instance = CountingCompare()
    from app.api import routes as routes_module

    monkeypatch.setattr(routes_module, "get_provider", lambda: instance)
    return CountingCompare


def test_compare_dedup_within_window(monkeypatch):
    counting = _counting_provider(monkeypatch)
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/assessments", data={"description": "楼道堆物堵塞疏散通道"}
        )
        assessment_id = created.json()["id"]
        submitted = client.post(
            f"/api/v1/assessments/{assessment_id}/rectification",
            data={"note": "已清理"},
            files=[("files", ("after.png", FAKE_PNG, "image/png"))],
        )
        assert submitted.status_code == 200
        assert counting.compare_calls == 1  # 提交时自动比对一次

        # 窗口内显式比对：复用缓存，不重复调用模型
        replay = client.post(f"/api/v1/assessments/{assessment_id}/rectification/compare")
        assert replay.status_code == 200
        assert counting.compare_calls == 1, "窗口内重复比对不应再次调用模型"

        # 窗口清零后：真实执行
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "compare_dedup_minutes", 0)
        fresh = client.post(f"/api/v1/assessments/{assessment_id}/rectification/compare")
        assert fresh.status_code == 200
        assert counting.compare_calls == 2


def test_compare_reruns_after_status_change(monkeypatch):
    counting = _counting_provider(monkeypatch)
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/assessments", data={"description": "楼道堆物堵塞疏散通道"}
        )
        assessment_id = created.json()["id"]
        client.post(
            f"/api/v1/assessments/{assessment_id}/rectification",
            data={"note": "已清理"},
            files=[("files", ("after.png", FAKE_PNG, "image/png"))],
        )
        assert counting.compare_calls == 1

        # 整改状态流转（pending_verification → verified）后比对语义变化，应真实执行
        confirmed = client.post(
            f"/api/v1/assessments/{assessment_id}/rectification/confirm",
            json={"resolved": True},
        )
        assert confirmed.status_code == 200
        client.post(f"/api/v1/assessments/{assessment_id}/rectification/compare")
        assert counting.compare_calls == 2, "整改状态变化后不应复用旧比对"
