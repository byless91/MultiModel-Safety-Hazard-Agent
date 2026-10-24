"""B4/WP2.4：基础限流——登录防爆破与研判提交频率。"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.rate_limit import limiter
from app.core.security import hash_password
from app.main import app
from app.models import User


@pytest.fixture(autouse=True)
def _reset_limiter():
    limiter.reset()
    yield
    limiter.reset()


def _enable_rate_limit(monkeypatch, **overrides):
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    for key, value in overrides.items():
        monkeypatch.setattr(settings, key, value)


def test_login_brute_force_limited(monkeypatch):
    _enable_rate_limit(monkeypatch, rate_limit_login_per_minute=3)
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "jwt")
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == "rate-target").first() is None:
            db.add(
                User(
                    username="rate-target",
                    password_hash=hash_password("password-123"),
                    role="reviewer",
                )
            )
            db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        statuses = [
            client.post(
                "/api/v1/auth/token",
                data={"username": "rate-target", "password": "wrong-password"},
            ).status_code
            for _ in range(4)
        ]
    assert statuses[:3] == [401, 401, 401]
    assert statuses[3] == 429, "连续失败登录应触发限流"


def test_assessment_submission_limited(monkeypatch):
    _enable_rate_limit(monkeypatch, rate_limit_assessments_per_minute=3)
    with TestClient(app) as client:
        statuses = [
            client.post(
                "/api/v1/assessments", data={"description": "楼道堆物堵塞疏散通道"}
            ).status_code
            for _ in range(4)
        ]
    assert statuses[:3] == [201, 201, 201]
    assert statuses[3] == 429, "超过频率的研判提交应触发限流"


def test_rate_limit_disabled_by_default():
    with TestClient(app) as client:
        statuses = [
            client.post(
                "/api/v1/assessments", data={"description": "楼道堆物堵塞疏散通道"}
            ).status_code
            for _ in range(6)
        ]
    assert all(code == 201 for code in statuses), "默认关闭时限流不得影响正常使用"
