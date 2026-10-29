"""M3: optional location, origin, event time and traceable imports."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.api import routes
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import Assessment, User
from sqlalchemy import delete, select

PREFIX = "M3_TEST_ONLY_"


@pytest.fixture
def records():
    created: list[str] = []
    yield created
    with SessionLocal() as db:
        if created:
            db.execute(delete(Assessment).where(Assessment.id.in_(created)))
        db.execute(delete(Assessment).where(Assessment.source_ref.like(f"{PREFIX}%")))
        db.commit()


def create(client, *, key=None, **fields):
    data = {"description": "M3_TEST_ONLY 楼道堆物影响疏散", "mode": "manual", **fields}
    headers = {"Idempotency-Key": key or f"m3-{uuid4().hex}"}
    response = client.post("/api/v1/assessments", data=data, headers=headers)
    return response


def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def test_manual_entry_keeps_location_source_and_event_time_separate(review_client, records):
    response = create(
        review_client, address="幸福路 3 号 2 单元", district="示例区", facility="居民楼", scene="楼道",
        latitude="30.123456", longitude="120.654321", coordinate_system="gcj02",
        data_source="simulated", event_time="2026-10-20T09:30:00+08:00",
    )
    assert response.status_code == 201, response.text
    item = response.json()
    records.append(item["id"])
    assert item["address"] == "幸福路 3 号 2 单元" and item["district"] == "示例区"
    assert item["facility"] == "居民楼" and item["scene"] == "楼道"
    assert item["latitude"] == 30.123456 and item["longitude"] == 120.654321
    assert item["coordinate_source"] == "manual" and item["coordinate_system"] == "gcj02"
    assert item["data_source"] == "simulated" and item["location_precision"] == "coordinate"
    assert utc(item["event_time"]) == datetime(2026, 10, 20, 1, 30, tzinfo=UTC)
    assert item["event_time"] != item["created_at"]


def test_missing_location_is_allowed_and_precision_stays_explicit(review_client, records):
    response = create(review_client)
    assert response.status_code == 201, response.text
    item = response.json()
    records.append(item["id"])
    assert item["address"] is None and item["district"] is None
    assert item["latitude"] is None and item["longitude"] is None
    assert item["data_source"] == "report" and item["event_time"] is None
    assert item["location_precision"] == "unknown"
    assert item["coordinate_source"] is None and item["coordinate_system"] is None

    district_only = create(review_client, district="示例区").json()
    records.append(district_only["id"])
    assert district_only["location_precision"] == "district"

    address_only = create(review_client, address="示例路 1 号").json()
    records.append(address_only["id"])
    assert address_only["location_precision"] == "address"


@pytest.mark.parametrize("fields", [
    {"latitude": "30.1"},
    {"longitude": "120.1"},
    {"latitude": "30.1", "longitude": "120.1"},
    {"coordinate_system": "wgs84"},
    {"event_time": "2026-10-20T09:30:00"},
])
def test_incomplete_or_naive_location_input_is_rejected(review_client, records, fields):
    response = create(review_client, **fields)
    assert response.status_code == 422, response.text


def test_import_deduplicates_and_reports_each_bad_row(review_client, records):
    rows = [
        {"source_ref": f"{PREFIX}IMP-1", "description": "公开案例一：楼道堆物", "data_source": "public_case",
         "district": "示例区", "address": "示例路 9 号", "latitude": 30.2, "longitude": 120.2,
         "coordinate_system": "wgs84", "event_time": "2026-10-18T10:00:00+08:00"},
        {"source_ref": f"{PREFIX}IMP-1", "description": "同一批次重复编号", "data_source": "public_case"},
        {"description": "缺少外部编号", "data_source": "public_case"},
        {"source_ref": f"{PREFIX}IMP-BAD", "description": "未知来源类型", "data_source": "guess"},
        {"source_ref": f"{PREFIX}IMP-2", "description": "模拟案例：仓库通道", "data_source": "simulated"},
        {"source_ref": f"{PREFIX}IMP-NODS", "description": "缺少数据来源"},
    ]
    response = review_client.post("/api/v1/assessments/import", json={"rows": rows})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["imported"] == 2
    assert result["duplicates"] == [2]
    assert [failure["row"] for failure in result["failures"]] == [3, 4, 6]
    assert "source_ref" in result["failures"][0]["reason"]
    assert "data_source" in result["failures"][1]["reason"]
    assert "data_source" in result["failures"][2]["reason"]

    with SessionLocal() as db:
        items = db.scalars(select(Assessment).where(
            Assessment.source_ref.in_([f"{PREFIX}IMP-1", f"{PREFIX}IMP-2"]))).all()
        assert len(items) == 2
        first = next(item for item in items if item.source_ref == f"{PREFIX}IMP-1")
        second = next(item for item in items if item.source_ref == f"{PREFIX}IMP-2")
        assert first.import_batch_id == second.import_batch_id == result["batch_id"]
        assert first.status == "imported" and first.confirmed is False
        assert first.record_mode == "imported" and first.coordinate_source == "import"
        assert first.data_source == "public_case" and first.event_time is not None
        assert utc(first.event_time.isoformat()) == datetime(2026, 10, 18, 2, 0, tzinfo=UTC)
        assert second.coordinate_source is None and second.latitude is None
        first_id = first.id

    detail = review_client.get(f"/api/v1/assessments/{first_id}").json()
    assert detail["record_mode"] == "imported" and detail["status"] == "imported"
    assert detail["location_precision"] == "coordinate" and detail["source_ref"] == f"{PREFIX}IMP-1"
    assert detail["import_batch_id"] == result["batch_id"]

    repeated = review_client.post("/api/v1/assessments/import", json={"rows": rows}).json()
    assert repeated["imported"] == 0
    assert repeated["duplicates"] == [1, 2, 5]
    assert [failure["row"] for failure in repeated["failures"]] == [3, 4, 6]
    assert repeated["batch_id"] != result["batch_id"]


@pytest.mark.parametrize("role", ["inspector", "reviewer"])
def test_import_is_limited_to_administrators(review_client, monkeypatch, role):
    with SessionLocal() as db:
        user = User(username=f"m3-{uuid4().hex}", role=role, password_hash="unused")
        db.add(user)
        db.commit()
        token = create_access_token(user)
    monkeypatch.setattr(routes.settings, "auth_mode", "jwt")
    review_client.headers["Authorization"] = f"Bearer {token}"
    try:
        response = review_client.post("/api/v1/assessments/import", json={"rows": [
            {"source_ref": f"{PREFIX}ROLE", "description": "越权导入", "data_source": "simulated"},
        ]})
        assert response.status_code == 403
    finally:
        review_client.headers.pop("Authorization", None)


def test_idempotency_key_binds_location_metadata(review_client, records):
    key = f"m3-{uuid4().hex}"
    first = create(review_client, key=key, address="示例路 1 号")
    assert first.status_code == 201, first.text
    records.append(first.json()["id"])
    changed = create(review_client, key=key, address="另一条路 2 号")
    assert changed.status_code == 409
