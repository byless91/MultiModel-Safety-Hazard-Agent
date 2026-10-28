"""R5/T14: startup configuration, explicit auth modes and static signed uploads."""

import hashlib
import hmac
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from app.cli.create_user import main as create_user
from app.core.config import Settings, get_settings
from app.core.security import sign_upload_url, verify_upload_signature
from fastapi import HTTPException
from pydantic import ValidationError

from _support.environment import create_environment

SECRET = "r5-config-test-secret-at-least-thirty-two-bytes"
STATIC = "r5-static-service-test-credential"


@pytest.mark.parametrize("mode", ["none", "token", "jwt"])
def test_valid_modes_are_explicit_settings(mode):
    configured = Settings(_env_file=None, auth_mode=mode, auth_jwt_secret=SECRET, api_bearer_token=STATIC)
    assert configured.auth_mode == mode


@pytest.mark.parametrize("values", [
    {"auth_mode": "jwt", "auth_jwt_secret": "dev-insecure-secret-change-me"},
    {"auth_mode": "jwt", "auth_jwt_secret": "change-me-to-a-long-random-secret"},
    {"auth_mode": "jwt", "auth_jwt_secret": "short"},
    {"auth_mode": "jwt", "auth_jwt_secret": " " * 40},
    {"auth_mode": "token", "api_bearer_token": ""},
    {"auth_mode": "token", "api_bearer_token": " bad-whitespace "},
])
def test_unsafe_settings_are_rejected_without_echoing_credentials(values):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, dashscope_api_key="fake-private-model-key", **values)
    assert "fake-private-model-key" not in str(error.value)


@pytest.mark.parametrize("mode", ["jwt", "token"])
def test_actual_app_import_refuses_invalid_startup_configuration(mode):
    environment = create_environment()
    overrides = {**os.environ, **environment.overrides, "AUTH_MODE": mode,
                 "AUTH_JWT_SECRET": "dev-insecure-secret-change-me", "API_BEARER_TOKEN": "",
                 "DASHSCOPE_API_KEY": "fake-private-model-key", "PYTHONIOENCODING": "utf-8",
                 "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "backend")}
    result = subprocess.run([sys.executable, "-c", "import app.main"], env=overrides, capture_output=True,
                            text=True, encoding="utf-8", timeout=15)
    assert result.returncode != 0 and "AUTH_MODE" in result.stderr
    assert "fake-private-model-key" not in result.stderr


@pytest.mark.parametrize("mode", ["none", "token", "jwt"])
def test_health_reports_concrete_mode_and_password_login_only_exists_for_jwt(review_client, monkeypatch, mode):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", mode)
    monkeypatch.setattr(settings, "api_bearer_token", STATIC)
    monkeypatch.setattr(settings, "auth_jwt_secret", SECRET)
    health = review_client.get("/api/v1/health").json()
    assert health["auth_mode"] == mode and health["auth_required"] == (mode != "none")
    if mode != "jwt":
        response = review_client.post("/api/v1/auth/token", data={"username": "anything", "password": "anything"})
        assert response.status_code == 409
    if mode == "none":
        assert review_client.get("/api/v1/auth/check").json()["authenticated"] is False
    elif mode == "token":
        assert review_client.get("/api/v1/auth/check").status_code == 401
        assert review_client.get("/api/v1/auth/check", headers={"Authorization": "Bearer bad"}).status_code == 401
        response = review_client.get("/api/v1/auth/check", headers={"Authorization": f"Bearer {STATIC}"})
        assert response.json() == {"auth_mode": "token", "authenticated": True}
        assert review_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {STATIC}"}).status_code == 403
    else:
        username = f"r5-user-{uuid4().hex[:8]}"
        assert create_user(["--username", username, "--role", "reviewer", "--password", "offline-password"]) == 0
        response = review_client.post("/api/v1/auth/token", data={"username": username, "password": "offline-password"})
        assert response.status_code == 200
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        assert review_client.get("/api/v1/auth/check", headers=headers).json()["authenticated"]
        assert review_client.get("/api/v1/auth/me", headers=headers).json()["username"] == username


@pytest.mark.parametrize("mode", ["jwt", "token"])
def test_signed_uploads_use_the_mode_secret_and_reject_forgery_and_expiry(monkeypatch, mode):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", mode)
    monkeypatch.setattr(settings, "auth_jwt_secret", SECRET)
    monkeypatch.setattr(settings, "api_bearer_token", STATIC)
    path = "/uploads/r5/example.png"
    signed = urlsplit(sign_upload_url(path))
    parameters = parse_qs(signed.query)
    expiry, signature = parameters["exp"][0], parameters["sig"][0]
    verify_upload_signature(path, expiry, signature)
    wrong_secret = "dev-insecure-secret-change-me"
    forged = hmac.new(wrong_secret.encode(), f"upload|{path}|{expiry}".encode(), hashlib.sha256).hexdigest()
    with pytest.raises(HTTPException) as error:
        verify_upload_signature(path, expiry, forged)
    assert error.value.status_code == 401
    with pytest.raises(HTTPException) as error:
        verify_upload_signature(path, "1", signature)
    assert error.value.status_code == 410
