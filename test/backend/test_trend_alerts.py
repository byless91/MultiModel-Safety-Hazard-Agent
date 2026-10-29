"""M5: explainable trend rule, historical replay, retained false-positive decisions."""

from collections import Counter
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from app.api import routes
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import Assessment, TrendAlert, User
from app.services.trends import (
    RULE_VERSION,
    evaluate,
    latest_complete_month,
    refresh_alerts,
    shift_month,
    trend_report,
)
from sqlalchemy import delete, select

PREFIX = "M5_TEST_ONLY_"
AS_OF = date(2026, 9, 1)


@pytest.fixture
def records():
    ids: list[str] = []
    yield ids
    with SessionLocal() as db:
        if ids:
            db.execute(delete(Assessment).where(Assessment.id.in_(ids)))
        db.execute(delete(TrendAlert).where(TrendAlert.scope_value.like(f"{PREFIX}%")))
        db.commit()


def make(records, category, month: date, count: int = 1, **fields):
    for index in range(count):
        values = {
            "description": f"{PREFIX}{category}-{month}-{index}", "status": "confirmed",
            "confirmed": True, "hazard_category": category, "risk_level": 1, "data_source": "report",
            "event_time": datetime(month.year, month.month, 10, tzinfo=UTC),
        }
        values.update(fields)
        with SessionLocal() as db:
            item = Assessment(**values)
            db.add(item)
            db.commit()
            records.append(item.id)


def seed_trigger(records, category=f"{PREFIX}电气线路隐患"):
    for offset in range(6, 0, -1):
        make(records, category, shift_month(AS_OF, -offset))
    make(records, category, AS_OF, count=5)
    return category


def test_insufficient_history_returns_a_clear_reason_and_no_alert(records):
    category = f"{PREFIX}资料不足"
    make(records, category, AS_OF, count=5)
    with SessionLocal() as db:
        assert refresh_alerts(db, as_of=AS_OF) == 0
        report = trend_report(db, as_of=AS_OF)
    assert report["sufficiency"]["supported"] is False
    assert "历史资料不足" in report["sufficiency"]["reason"]
    assert report["evaluations"][0]["sufficient"] is False
    assert "少于 10 条" in report["evaluations"][0]["reason"]
    assert report["alerts"] == []


def test_rule_triggers_with_sample_size_and_does_not_duplicate(records, review_client):
    category = seed_trigger(records)
    with SessionLocal() as db:
        assert refresh_alerts(db, as_of=AS_OF) == 1
        assert refresh_alerts(db, as_of=AS_OF) == 0
        report = trend_report(db, as_of=AS_OF)
    assert report["as_of"] == "2026-09"
    assert report["rule"]["version"] == RULE_VERSION and report["rule"]["ratio_threshold"] == 2.0
    assert report["sufficiency"]["supported"] is True
    alert = report["alerts"][0]
    assert alert["scope_value"] == category and alert["month"] == "2026-09"
    assert alert["observed"] == 5 and alert["baseline"] == 1.0 and alert["sample_size"] == 11
    assert "月均 1.0 条" in alert["explanation"] and "样本 11 条" in alert["explanation"]
    assert alert["status"] == "open"
    assert report["backtest"]["months_evaluated"] == 1
    assert report["backtest"]["triggered"] == 1
    assert report["backtest"]["sample_size"] == 11
    assert "不是预测准确率" in report["backtest"]["note"]

    reviewed = review_client.post(f"/api/v1/analytics/trend-alerts/{alert['id']}", json={
        "status": "false_positive", "note": "M5_TEST_ONLY 现场核查为集中排查",
    })
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "false_positive"
    assert reviewed.json()["note"] == "M5_TEST_ONLY 现场核查为集中排查"
    with SessionLocal() as db:
        assert refresh_alerts(db, as_of=AS_OF) == 0
        after = trend_report(db, as_of=AS_OF)
    assert after["false_positive_count"] == 1
    assert after["alerts"][0]["status"] == "false_positive"


def test_sparse_category_is_listed_as_insufficient_while_supported_category_still_alerts(records):
    seed_trigger(records)
    sparse = f"{PREFIX}稀疏类别"
    make(records, sparse, AS_OF, count=2)
    with SessionLocal() as db:
        refresh_alerts(db, as_of=AS_OF)
        report = trend_report(db, as_of=AS_OF)
    sparse_eval = next(row for row in report["evaluations"] if row["category"] == sparse)
    assert sparse_eval["sufficient"] is False and "历史资料不足" not in sparse_eval["reason"]
    assert report["sufficiency"]["supported"] is True
    assert report["sufficiency"]["categories_sufficient"] == 1
    assert any(alert["scope_value"] != sparse for alert in report["alerts"])


def test_simulated_records_never_drive_trend_alerts(records):
    category = f"{PREFIX}模拟类别"
    for offset in range(6, 0, -1):
        make(records, category, shift_month(AS_OF, -offset), data_source="simulated")
    make(records, category, AS_OF, count=5, data_source="simulated")
    with SessionLocal() as db:
        assert refresh_alerts(db, as_of=AS_OF) == 0
        report = trend_report(db, as_of=AS_OF)
    assert report["alerts"] == []
    assert all(row["category"] != category for row in report["evaluations"])
    assert report["sufficiency"]["supported"] is False


def test_rule_uses_previous_complete_month_and_follows_are_replay_not_prediction():
    assert latest_complete_month(datetime(2026, 10, 30, tzinfo=UTC)) == date(2026, 9, 1)
    counts = Counter({"2026-03": 1, "2026-04": 1, "2026-05": 1, "2026-06": 1,
                      "2026-07": 1, "2026-08": 1, "2026-09": 5})
    result = evaluate(counts, AS_OF)
    assert result == {"observed": 5, "baseline": 1.0, "sample_size": 11,
                      "sufficient": True, "triggered": True, "reason": ""}


@pytest.mark.parametrize("role, expected", [("inspector", 403), ("reviewer", 200)])
def test_trend_alerts_require_reviewer_or_admin(review_client, monkeypatch, role, expected):
    with SessionLocal() as db:
        user = User(username=f"m5-{uuid4().hex}", role=role, password_hash="unused")
        db.add(user)
        db.commit()
        token = create_access_token(user)
    monkeypatch.setattr(routes.settings, "auth_mode", "jwt")
    review_client.headers["Authorization"] = f"Bearer {token}"
    try:
        assert review_client.get("/api/v1/analytics/trend-alerts").status_code == expected
        assert review_client.post("/api/v1/analytics/trend-alerts/refresh").status_code == expected
        with SessionLocal() as db:
            alert = db.scalars(select(TrendAlert)).first()
        if alert and role == "inspector":
            reviewed = review_client.post(f"/api/v1/analytics/trend-alerts/{alert.id}", json={
                "status": "acknowledged", "note": "",
            })
            assert reviewed.status_code == 403
    finally:
        review_client.headers.pop("Authorization", None)
