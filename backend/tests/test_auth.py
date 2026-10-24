"""B4/WP2.1-2.3：JWT 用户体系、角色权限、审计身份与签名文件 URL。

none 模式（默认）全开放的兼容性由既有 316 项测试隐式覆盖；
本文件显式验证 jwt/token 模式的安全合同。
"""


from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import User

FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 48


def _enable_jwt(monkeypatch, secret="test-secret-b4"):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "jwt")
    monkeypatch.setattr(settings, "auth_jwt_secret", secret)


def _make_user(username: str, role: str, password: str = "password-123") -> None:
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == username).first() is None:
            db.add(User(username=username, password_hash=hash_password(password), role=role))
            db.commit()
    finally:
        db.close()


def _login(client: TestClient, username: str, password: str = "password-123"):
    return client.post("/api/v1/auth/token", data={"username": username, "password": password})


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_health_reports_auth_required(monkeypatch):
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json()["auth_required"] is False
    _enable_jwt(monkeypatch)
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json()["auth_required"] is True


def test_login_me_and_wrong_password(monkeypatch):
    _enable_jwt(monkeypatch)
    _make_user("reviewer-a", "reviewer")
    with TestClient(app) as client:
        ok = _login(client, "reviewer-a")
        assert ok.status_code == 200
        body = ok.json()
        assert body["token_type"] == "bearer"
        assert body["user"]["username"] == "reviewer-a"
        assert body["user"]["role"] == "reviewer"

        me = client.get("/api/v1/auth/me", headers=_auth(body["access_token"]))
        assert me.status_code == 200
        assert me.json()["username"] == "reviewer-a"

        wrong = _login(client, "reviewer-a", "wrong-password")
        assert wrong.status_code == 401
        missing = _login(client, "no-such-user")
        assert missing.status_code == 401
        assert missing.json()["detail"] == wrong.json()["detail"]  # 统一文案不暴露存在性


def test_guarded_routes_require_token(monkeypatch):
    _enable_jwt(monkeypatch)
    with TestClient(app) as client:
        no_token = client.get("/api/v1/assessments")
        bad_token = client.get(
            "/api/v1/assessments", headers=_auth("not-a-jwt")
        )
    assert no_token.status_code == 401
    assert bad_token.status_code == 401


def test_role_gates_confirm_and_knowledge(monkeypatch):
    _enable_jwt(monkeypatch)
    _make_user("insp-1", "inspector")
    _make_user("rev-1", "reviewer")
    _make_user("adm-1", "admin")
    with TestClient(app) as client:
        insp_token = _login(client, "insp-1").json()["access_token"]
        rev_token = _login(client, "rev-1").json()["access_token"]
        adm_token = _login(client, "adm-1").json()["access_token"]

        # inspector 可提交研判
        created = client.post(
            "/api/v1/assessments",
            data={"description": "小区楼道堆放纸箱杂物，堵塞疏散通道"},
            headers=_auth(insp_token),
        )
        assert created.status_code == 201
        assessment_id = created.json()["id"]

        # inspector 不能复核确认
        denied = client.post(
            f"/api/v1/assessments/{assessment_id}/confirm",
            json={"confirmed": True},
            headers=_auth(insp_token),
        )
        assert denied.status_code == 403

        # reviewer 可以
        allowed = client.post(
            f"/api/v1/assessments/{assessment_id}/confirm",
            json={"confirmed": True},
            headers=_auth(rev_token),
        )
        assert allowed.status_code == 200

        # 知识库上传：inspector/reviewer 403，admin 201
        doc = {"title": "测试", "source": "s"}
        files = [("file", ("law.txt", "第二十八条 禁止占用疏散通道。".encode(), "text/plain"))]
        assert client.post(
            "/api/v1/knowledge/documents", data=doc, files=files, headers=_auth(insp_token)
        ).status_code == 403
        assert client.post(
            "/api/v1/knowledge/documents", data=doc, files=files, headers=_auth(rev_token)
        ).status_code == 403
        assert client.post(
            "/api/v1/knowledge/documents", data=doc, files=files, headers=_auth(adm_token)
        ).status_code == 201

        # 用户管理仅 admin
        assert client.get("/api/v1/admin/users", headers=_auth(insp_token)).status_code == 403
        assert client.get("/api/v1/admin/users", headers=_auth(adm_token)).status_code == 200


def test_audit_identity_cannot_be_forged(monkeypatch):
    _enable_jwt(monkeypatch)
    _make_user("rev-2", "reviewer")
    with TestClient(app) as client:
        token = _login(client, "rev-2").json()["access_token"]
        created = client.post(
            "/api/v1/assessments",
            data={"description": "楼道堆物堵塞疏散通道"},
            headers=_auth(token),
        )
        assessment_id = created.json()["id"]
        confirmed = client.post(
            f"/api/v1/assessments/{assessment_id}/confirm",
            # 伪造 reviewer 字段：jwt 模式下必须被认证身份覆盖
            json={"confirmed": True, "reviewer": "伪造的复核员"},
            headers=_auth(token),
        )
        assert confirmed.status_code == 200
        body = confirmed.json()
        assert body["human_review"]["resolution"]["reviewer"] == "rev-2"

        from app.core.db import SessionLocal
        from app.models import Assessment

        db = SessionLocal()
        try:
            row = db.get(Assessment, assessment_id)
            assert row.confirmed_by_name == "rev-2"
            assert row.confirmed_by_id
        finally:
            db.close()


def test_password_hash_never_leaks(monkeypatch):
    _enable_jwt(monkeypatch)
    _make_user("rev-3", "reviewer")
    _make_user("adm-3", "admin")
    with TestClient(app) as client:
        login_body = _login(client, "rev-3").text
        adm_token = _login(client, "adm-3").json()["access_token"]
        users_body = client.get("/api/v1/admin/users", headers=_auth(adm_token)).text
    assert "$2b$" not in login_body, "登录响应不得包含 bcrypt 哈希"
    assert "$2b$" not in users_body, "用户列表不得包含密码哈希"
    assert "password" not in users_body.replace("password_hashless", "").replace(
        "must_not_appear", ""
    ) or "password_hash" not in users_body


def test_upload_urls_are_signed_and_protected(monkeypatch):
    _enable_jwt(monkeypatch)
    _make_user("insp-2", "inspector")
    with TestClient(app) as client:
        token = _login(client, "insp-2").json()["access_token"]
        created = client.post(
            "/api/v1/assessments",
            data={"description": "楼道堆物堵塞疏散通道"},
            files=[("files", ("scene.png", FAKE_PNG, "image/png"))],
            headers=_auth(token),
        )
        assert created.status_code == 201
        url = created.json()["images"][0]["url"]
        assert "exp=" in url and "sig=" in url, "jwt 模式下图片 URL 必须带签名"

        # 带签名可访问，内容一致
        fetched = client.get(url)
        assert fetched.status_code == 200
        assert fetched.content == FAKE_PNG

        # 去掉签名 → 401；篡改签名 → 401
        base = url.split("?")[0]
        assert client.get(base).status_code == 401
        tampered = base + "?exp=9999999999&sig=deadbeef"
        assert client.get(tampered).status_code == 401

        # 过期签名 → 410（TTL 置负后新生成的 URL 立即过期）
        monkeypatch.setattr(get_settings(), "upload_url_ttl_minutes", -10)
        created2 = client.post(
            "/api/v1/assessments",
            data={"description": "楼道堆物堵塞疏散通道"},
            files=[("files", ("scene.png", FAKE_PNG, "image/png"))],
            headers=_auth(token),
        )
        expired_url = created2.json()["images"][0]["url"]
        assert client.get(expired_url).status_code == 410


def test_none_mode_uploads_stay_plain():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/assessments",
            data={"description": "楼道堆物堵塞疏散通道"},
            files=[("files", ("scene.png", FAKE_PNG, "image/png"))],
        )
        url = created.json()["images"][0]["url"]
        assert "?" not in url, "none 模式不需要签名"
        assert client.get(url).status_code == 200
