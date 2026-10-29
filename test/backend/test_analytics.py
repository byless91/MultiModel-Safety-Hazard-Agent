"""M4: confirmed-record distributions, trend, map points and rectification benchmarks."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.api import routes
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import Assessment, User
from app.services.analytics import bd09_to_wgs84, gcj02_to_wgs84, to_wgs84, wgs84_to_gcj02
from sqlalchemy import delete

PREFIX = "M4_TEST_ONLY_"


@pytest.fixture
def records():
    ids: list[str] = []
    yield ids
    with SessionLocal() as db:
        if ids:
            db.execute(delete(Assessment).where(Assessment.id.in_(ids)))
        db.execute(delete(Assessment).where(Assessment.source_ref.like(f"{PREFIX}%")))
        db.commit()


def make(ids: list[str], **fields) -> str:
    values = {
        "description": f"{PREFIX}记录", "status": "confirmed", "confirmed": True,
        "hazard_category": "占用疏散通道", "risk_level": 1, "data_source": "report",
    }
    values.update(fields)
    with SessionLocal() as db:
        item = Assessment(**values)
        db.add(item)
        db.commit()
        ids.append(item.id)
        return item.id


def overview(client, **params):
    response = client.get("/api/v1/analytics/overview", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_overview_matches_hand_counts_with_zero_months_and_ungraded(records, review_client):
    a = make(records, district="甲区", hazard_category="占用疏散通道", risk_level=1,
             event_time=datetime(2026, 1, 10, tzinfo=UTC),
             latitude=30.1, longitude=120.1, coordinate_system="wgs84")
    b = make(records, district="甲区", hazard_category="消防器材失效", risk_level=None,
             event_time=datetime(2026, 3, 5, tzinfo=UTC),
             latitude=30.2, longitude=120.2, coordinate_system="gcj02")
    make(records, district="乙区", hazard_category="占用疏散通道", risk_level=3,
         created_at=datetime(2026, 3, 15, tzinfo=UTC))
    make(records, district="乙区", hazard_category=None, risk_level=2,
         event_time=datetime(2026, 4, 20, tzinfo=UTC))
    make(records, district="甲区", status="awaiting_human_review", confirmed=False,
         event_time=datetime(2026, 2, 1, tzinfo=UTC))
    imported = review_client.post("/api/v1/assessments/import", json={"rows": [{
        "source_ref": f"{PREFIX}PUBLIC-1", "description": "M4_TEST_ONLY 公开案例",
        "data_source": "public_case", "event_time": "2026-02-03T00:00:00+08:00",
    }]})
    assert imported.status_code == 200 and imported.json()["imported"] == 1

    data = overview(review_client)
    assert data["total"] == 4
    assert {row["value"]: row["count"] for row in data["by_district"]} == {"甲区": 2, "乙区": 2}
    assert {row["value"]: row["count"] for row in data["by_category"]} == {
        "占用疏散通道": 2, "消防器材失效": 1, "未填写": 1,
    }
    assert {row["value"]: row["count"] for row in data["by_risk"]} == {
        "1": 1, "2": 1, "3": 1, "ungraded": 1,
    }
    assert [(row["month"], row["count"]) for row in data["months"]] == [
        ("2026-01", 1), ("2026-02", 0), ("2026-03", 2), ("2026-04", 1),
    ]
    assert {row["value"]: row["count"] for row in data["by_source"]} == {"report": 4}
    assert data["collected"] == [{"value": "public_case", "label": "公开案例", "count": 1}]
    points = {point["id"]: point for point in data["map_points"]}
    assert set(points) == {a, b}
    assert points[a]["map_latitude"] == pytest.approx(30.1)
    assert points[b]["map_longitude"] != pytest.approx(120.2)
    assert data["map_truncated"] is False
    assert "已确认" in data["notice"] and "风险排名" in data["notice"]


def test_filters_and_new_confirmation_are_visible_immediately(records, review_client):
    make(records, district="甲区", hazard_category="占用疏散通道", risk_level=1,
         event_time=datetime(2026, 1, 10, tzinfo=UTC))
    make(records, district="乙区", hazard_category="消防器材失效", risk_level=2,
         event_time=datetime(2026, 2, 10, tzinfo=UTC))
    pending = make(records, district="甲区", status="awaiting_human_review", confirmed=False,
                   event_time=datetime(2026, 1, 20, tzinfo=UTC))
    assert overview(review_client)["total"] == 2
    filtered = overview(review_client, district="甲区", start="2026-01", end="2026-01")
    assert filtered["total"] == 1
    assert filtered["by_district"] == [{"value": "甲区", "label": "甲区", "count": 1}]
    assert [row["month"] for row in filtered["months"]] == ["2026-01"]

    with SessionLocal() as db:
        item = db.get(Assessment, pending)
        item.confirmed = True
        item.status = "confirmed"
        db.commit()
    assert overview(review_client)["total"] == 3
    assert overview(review_client, district="甲区")["total"] == 2
    assert overview(review_client, category="消防器材失效")["total"] == 1
    assert overview(review_client, start="2026-03")["total"] == 0
    assert overview(review_client, start="2026-03")["months"] == [{"month": "2026-03", "count": 0}]


@pytest.mark.parametrize("params", [{"start": "2026-13"}, {"start": "2026-02", "end": "2026-01"}])
def test_invalid_month_ranges_are_rejected(review_client, params):
    assert review_client.get("/api/v1/analytics/overview", params=params).status_code == 422


def test_benchmarks_show_filters_sample_sources_and_comparability(records, review_client):
    both = make(records, description="M4_TEST_ONLY 两者一致", district="甲区", facility="居民楼",
                scene="楼道", hazard_category="占用疏散通道", rectification_status="verified",
                rectification_note="清理堆物并复检", data_source="report")
    make(records, description="M4_TEST_ONLY 仅设施一致", district="乙区", facility="居民楼",
         scene="仓库", hazard_category="占用疏散通道",
         rectification_status="rectifying", data_source="report")
    make(records, description="M4_TEST_ONLY 仅场景一致", district="丙区", facility="市场",
         scene="楼道", hazard_category="占用疏散通道", rectification_note="已安排清理",
         data_source=None)
    make(records, description="M4_TEST_ONLY 无整改信息", district="甲区", facility="居民楼", scene="楼道")
    make(records, description="M4_TEST_ONLY 未确认", district="甲区", facility="居民楼", scene="楼道",
         status="awaiting_human_review", confirmed=False, rectification_note="不应出现")
    make(records, description="M4_TEST_ONLY 类别不符", district="甲区", facility="居民楼", scene="楼道",
         hazard_category="消防器材失效", rectification_note="类别锁定")

    response = review_client.get("/api/v1/analytics/benchmarks", params={
        "facility": "居民楼", "scene": "楼道", "category": "占用疏散通道",
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["filters"] == {"facility": "居民楼", "scene": "楼道", "category": "占用疏散通道"}
    assert data["sample_size"] == 3 and data["returned"] == 3 and data["truncated"] is False
    assert [item["id"] for item in data["items"]][0] == both
    assert sorted(item["match"] for item in data["items"]) == ["both", "facility", "scene"]
    assert data["items"][0]["comparable"] == "设施与场景一致"
    assert {row["value"]: row["count"] for row in data["sources"]} == {"report": 2, "unknown": 1}
    assert "不能据此直接作出处置决定" in data["notice"]
    assert review_client.get("/api/v1/analytics/benchmarks").status_code == 422


@pytest.mark.parametrize("role, expected", [("inspector", 403), ("reviewer", 200)])
def test_analytics_requires_reviewer_or_admin(records, review_client, monkeypatch, role, expected):
    make(records, district="甲区")
    with SessionLocal() as db:
        user = User(username=f"m4-{uuid4().hex}", role=role, password_hash="unused")
        db.add(user)
        db.commit()
        token = create_access_token(user)
    monkeypatch.setattr(routes.settings, "auth_mode", "jwt")
    review_client.headers["Authorization"] = f"Bearer {token}"
    try:
        response = review_client.get("/api/v1/analytics/overview")
        assert response.status_code == expected, response.text
        assert review_client.get("/api/v1/analytics/benchmarks", params={"facility": "居民楼"}).status_code == expected
        assert review_client.get("/api/v1/analytics/options").status_code == expected
    finally:
        review_client.headers.pop("Authorization", None)


def test_options_expose_only_confirmed_dimensions(records, review_client):
    make(records, district="甲区", hazard_category="占用疏散通道", facility="居民楼", scene="楼道")
    make(records, district="乙区", status="awaiting_human_review", confirmed=False,
         hazard_category="消防器材失效", facility="仓库", scene="仓库")
    options = review_client.get("/api/v1/analytics/options").json()
    assert options == {"districts": ["甲区"], "categories": ["占用疏散通道"],
                       "facilities": ["居民楼"], "scenes": ["楼道"]}


def test_gcj02_and_bd09_coordinates_are_converted_for_the_map():
    wgs = (39.908823, 116.397470)
    gcj = wgs84_to_gcj02(*wgs)
    assert gcj == pytest.approx((39.910226, 116.403753), abs=5e-5)
    assert gcj02_to_wgs84(*gcj) == pytest.approx(wgs, abs=1e-5)
    assert bd09_to_wgs84(39.915, 116.404) == pytest.approx(
        gcj02_to_wgs84(39.908656, 116.397627), abs=1e-6)
    assert to_wgs84(*wgs, "wgs84") == wgs
    assert to_wgs84(*wgs, None) == wgs


def test_unconfirmed_and_imported_records_never_enter_confirmed_statistics(records, review_client):
    make(records, status="awaiting_human_review", confirmed=False)
    review_client.post("/api/v1/assessments/import", json={"rows": [{
        "source_ref": f"{PREFIX}SIM-1", "description": "M4_TEST_ONLY 模拟", "data_source": "simulated",
    }]})
    data = overview(review_client)
    assert data["total"] == 0 and data["months"] == []
    assert {row["value"]: row["count"] for row in data["collected"]} == {"simulated": 1}
