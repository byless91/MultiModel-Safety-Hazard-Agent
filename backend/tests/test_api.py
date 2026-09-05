import os
import re
import sqlite3

from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["provider"] == "mock"
    assert data["rag_loaded"] is True


def test_create_assessment_completes():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/assessments",
            data={"description": "小区楼道堆放纸箱杂物，堵塞疏散通道，通行明显受阻"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["hazard_category"] == "占用疏散通道"
    assert data["risk_level"] == 1
    assert data["confidence"] >= 0.8
    assert data["status"] == "completed"
    assert data["evidence"]


def test_followup_and_confirm_flow():
    with TestClient(app) as client:
        created = client.post("/api/v1/assessments", data={"description": "现场有异常"})
        assert created.status_code == 201
        first = created.json()
        assert first["status"] == "needs_more_info"
        assert first["followup_questions"]

        followup = client.post(
            f"/api/v1/assessments/{first['id']}/followup",
            json={"answer": "楼道堆放了大量纸箱，影响疏散通道通行"},
        )
        assert followup.status_code == 200
        second = followup.json()
        assert second["hazard_category"] == "占用疏散通道"
        assert second["followup_used"] == 1

        confirmed = client.post(
            f"/api/v1/assessments/{first['id']}/confirm",
            json={"confirmed": True, "edits": {"conclusion": "人工确认：楼道堆物需立即清理"}},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "confirmed"


def test_list_assessments():
    with TestClient(app) as client:
        client.post("/api/v1/assessments", data={"description": "灭火器压力表指针在红区"})
        response = client.get("/api/v1/assessments")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_rectification_flow():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/assessments",
            data={"description": "楼道堆物堵塞疏散通道"},
        )
        assessment_id = created.json()["id"]
        submitted = client.post(
            f"/api/v1/assessments/{assessment_id}/rectification",
            data={"note": "已清理疏散通道"},
            files=[("files", ("after.jpg", b"fake-image-bytes", "image/jpeg"))],
        )
        assert submitted.status_code == 200
        body = submitted.json()
        assert body["rectification_status"] == "under_review"
        assert body["images"][-1]["image_kind"] == "rectification"
        assert body["rectification_score"] is not None
        assert body["rectification_analysis"] is not None

        confirmed = client.post(
            f"/api/v1/assessments/{assessment_id}/rectification/confirm",
            json={"resolved": True},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["rectification_status"] == "resolved"


def test_rectification_compare_endpoint():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/assessments",
            data={"description": "楼道堆物堵塞疏散通道"},
        )
        assessment_id = created.json()["id"]
        client.post(
            f"/api/v1/assessments/{assessment_id}/rectification",
            data={"note": "整改后重新比对"},
            files=[("files", ("after.jpg", b"fake-image-bytes", "image/jpeg"))],
        )
        response = client.post(
            f"/api/v1/assessments/{assessment_id}/rectification/compare",
        )
    assert response.status_code == 200
    body = response.json()
    assert body["rectification_score"] is not None
    assert body["rectification_analysis"]["summary"]


def test_knowledge_rebuild():
    with TestClient(app) as client:
        response = client.post("/api/v1/knowledge/rebuild")
    assert response.status_code == 200
    body = response.json()
    assert body["chunks"] > 0
    assert "records" in body


def test_list_with_legacy_null_image_kind():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/assessments",
            data={"description": "楼道堆物堵塞疏散通道"},
            files=[("files", ("before.jpg", b"fake-image-bytes", "image/jpeg"))],
        )
        assessment_id = created.json()["id"]
        db_path = re.sub(r"^sqlite:///", "", os.environ["DATABASE_URL"])
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE assessment_images SET image_kind=NULL WHERE assessment_id=?",
            (assessment_id,),
        )
        conn.commit()
        conn.close()

        response = client.get("/api/v1/assessments")
    assert response.status_code == 200
    body = response.json()
    assert any(item["id"] == assessment_id for item in body)
