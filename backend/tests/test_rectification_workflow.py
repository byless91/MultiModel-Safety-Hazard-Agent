from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.services.rectification import (
    RectificationTransitionError,
    next_rectification_states,
    normalize_rectification_status,
    rectification_history,
    submit_rectification_photos,
    transition_rectification,
)

TINY_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


def _item(status: str | None = None, meta: str | None = None):
    return SimpleNamespace(
        rectification_status=status,
        rectification_meta_json=meta,
    )


def test_status_normalization_and_next_states():
    assert normalize_rectification_status(None) == "open"
    assert normalize_rectification_status("under_review") == "pending_verification"
    assert normalize_rectification_status("resolved") == "verified"
    assert normalize_rectification_status("rectifying") == "rectifying"
    assert next_rectification_states("open") == ["assigned", "rectifying"]
    assert next_rectification_states("pending_verification") == [
        "verified",
        "rectifying",
    ]
    assert next_rectification_states("closed") == ["open"]


def test_transition_path_records_full_history():
    item = _item()
    target = submit_rectification_photos(
        item,
        note="上传整改照片",
        by="ops",
    )
    assert target == "pending_verification"
    assert item.rectification_status == "pending_verification"
    history = rectification_history(item)
    assert [entry["to_status"] for entry in history] == [
        "assigned",
        "rectifying",
        "pending_verification",
    ]
    assert history[-1]["note"] == "上传整改照片"
    assert history[-1]["by"] == "ops"


def test_verified_to_closed_transition():
    item = _item("verified")
    assert transition_rectification(item, "closed", by="user") == "closed"
    assert item.rectification_status == "closed"


def test_invalid_transition_raises():
    item = _item("closed")
    try:
        transition_rectification(item, "verified")
    except RectificationTransitionError as exc:
        assert "非法整改状态流转" in str(exc)
    else:
        raise AssertionError("expected RectificationTransitionError")


def test_api_full_rectification_state_machine_flow():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/assessments",
            data={"description": "楼道堆物堵塞疏散通道"},
        )
        assessment_id = created.json()["id"]
        assert created.json()["rectification_status"] == "open"
        assert created.json()["rectification_next_states"] == [
            "assigned",
            "rectifying",
        ]

        started = client.post(
            f"/api/v1/assessments/{assessment_id}/rectification/transition",
            json={"to_status": "rectifying", "note": "开始整改"},
        )
        assert started.status_code == 200
        started_body = started.json()
        assert started_body["rectification_status"] == "rectifying"
        assert "verified" not in started_body["rectification_next_states"]

        submitted = client.post(
            f"/api/v1/assessments/{assessment_id}/rectification",
            data={"note": "已清理疏散通道"},
            files=[("files", ("after.png", TINY_PNG, "image/png"))],
        )
        assert submitted.status_code == 200
        body = submitted.json()
        assert body["rectification_status"] == "pending_verification"
        assert body["rectification_next_states"] == ["verified", "rectifying"]
        assert len(body["rectification_meta"]["history"]) >= 2
        assert body["rectification_score"] is not None
        assert (
            body["rectification_analysis"]["assessment"]["verdict"]
            in ("not_resolved", "needs_review", "resolved_recommended", "insufficient_evidence")
        )

        verified = client.post(
            f"/api/v1/assessments/{assessment_id}/rectification/transition",
            json={"to_status": "verified"},
        )
        assert verified.status_code == 200
        assert verified.json()["rectification_status"] == "verified"

        closed = client.post(
            f"/api/v1/assessments/{assessment_id}/rectification/transition",
            json={"to_status": "closed"},
        )
        assert closed.status_code == 200
        assert closed.json()["rectification_status"] == "closed"
        assert closed.json()["rectification_next_states"] == ["open"]

        reopened = client.post(
            f"/api/v1/assessments/{assessment_id}/rectification/transition",
            json={"to_status": "open"},
        )
        assert reopened.status_code == 200
        assert reopened.json()["rectification_status"] == "open"


def test_api_rejects_invalid_rectification_transition():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/assessments",
            data={"description": "灭火器压力表指针在红区"},
        )
        assessment_id = created.json()["id"]
        response = client.post(
            f"/api/v1/assessments/{assessment_id}/rectification/transition",
            json={"to_status": "verified"},
        )
        assert response.status_code == 409
        assert "非法整改状态流转" in response.json()["detail"]


def test_api_rejects_closing_before_human_verification():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/assessments",
            data={"description": "楼道堆物堵塞疏散通道"},
        )
        assessment_id = created.json()["id"]
        response = client.post(
            f"/api/v1/assessments/{assessment_id}/rectification/transition",
            json={"to_status": "closed"},
        )
        assert response.status_code == 409
        assert "非法整改状态流转" in response.json()["detail"]


def test_compare_without_photos_returns_explicit_no_evidence():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/assessments",
            data={"description": "楼道堆物堵塞疏散通道"},
        )
        assessment_id = created.json()["id"]
        response = client.post(
            f"/api/v1/assessments/{assessment_id}/rectification/compare",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["rectification_score"] is None
        assert "暂无整改后照片" in body["rectification_analysis"]["summary"]
        assert body["rectification_analysis"]["comparison"]["pair_count"] == 0
        assert body["rectification_analysis"]["assessment"]["verdict"] == "insufficient_evidence"


def test_comparison_meta_pairs_images_by_upload_order():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/assessments",
            data={"description": "楼道堆物堵塞疏散通道"},
            files=[
                ("files", ("before-1.png", TINY_PNG, "image/png")),
                ("files", ("before-2.png", TINY_PNG, "image/png")),
            ],
        )
        assessment_id = created.json()["id"]
        submitted = client.post(
            f"/api/v1/assessments/{assessment_id}/rectification",
            data={"note": "已清理疏散通道"},
            files=[
                ("files", ("after-1.png", TINY_PNG, "image/png")),
                ("files", ("after-2.png", TINY_PNG, "image/png")),
            ],
        )
        assert submitted.status_code == 200
        comparison = submitted.json()["rectification_analysis"]["comparison"]
        assert comparison["original_count"] == 2
        assert comparison["rectification_count"] == 2
        assert comparison["pair_count"] == 2
        assert comparison["unmatched_original_count"] == 0
        assert comparison["unmatched_rectification_count"] == 0
        assert len(comparison["paired"]) == 2
        assert comparison["paired"][0]["original_url"]
        assert comparison["paired"][0]["rectification_url"]
        assert (
            submitted.json()["rectification_analysis"]["assessment"]["verdict"]
            == "resolved_recommended"
        )


def test_comparison_meta_reports_unmatched_images():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/assessments",
            data={"description": "楼道堆物堵塞疏散通道"},
            files=[("files", ("before-1.png", TINY_PNG, "image/png"))],
        )
        assessment_id = created.json()["id"]
        submitted = client.post(
            f"/api/v1/assessments/{assessment_id}/rectification",
            data={"note": "已清理疏散通道"},
            files=[
                ("files", ("after-1.png", TINY_PNG, "image/png")),
                ("files", ("after-2.png", TINY_PNG, "image/png")),
            ],
        )
        assert submitted.status_code == 200
        comparison = submitted.json()["rectification_analysis"]["comparison"]
        assert comparison["original_count"] == 1
        assert comparison["rectification_count"] == 2
        assert comparison["pair_count"] == 1
        assert comparison["unmatched_rectification_count"] == 1
