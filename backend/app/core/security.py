"""认证与授权核心（B4/WP2.1-2.3）。

三种 AUTH_MODE：
- none：本地开发不鉴权（生产禁止）；
- token：静态 Bearer（兼容旧部署，已标记 deprecated）；
- jwt：用户体系——/api/v1/auth/token 换取 JWT，路由级角色校验。

审计与签名共用 auth_jwt_secret；密码只存 bcrypt 哈希，任何响应与日志
不得出现明文或哈希（test_auth.py 断言）。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from typing import Annotated, Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.models import User

logger = logging.getLogger("safety_hazard.auth")

ROLE_ADMIN = "admin"
ROLE_REVIEWER = "reviewer"
ROLE_INSPECTOR = "inspector"
ALL_ROLES = (ROLE_ADMIN, ROLE_REVIEWER, ROLE_INSPECTOR)


# ---------- 密码哈希 ----------


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


# ---------- JWT ----------


def create_access_token(user: User, *, secret: str | None = None, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "exp": int(time.time()) + (expires_minutes or settings.auth_token_expire_minutes) * 60,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, secret or settings.auth_jwt_secret, algorithm="HS256")


def _decode_token(token: str, *, secret: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            secret or settings.auth_jwt_secret,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="无效的访问凭证") from exc


# ---------- 路由守卫（挂在 APIRouter 级） ----------


async def authenticate(request: Request, db: Session = Depends(get_db)) -> User | None:
    """统一认证守卫：按 AUTH_MODE 校验并把身份缓存到 request.state。

    - none：直接放行，request.state.auth_user = None；
    - token：静态 Bearer 常量时间比较（兼容旧部署）；
    - jwt：解析 JWT 并加载用户（disabled 用户拒绝）。
    """
    settings = get_settings()
    if settings.auth_mode == "none":
        request.state.auth_user = None
        return None

    header = request.headers.get("Authorization") or ""
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供访问凭证")
    credential = header[len("Bearer "):].strip()

    if settings.auth_mode == "token":
        expected = (get_settings().api_bearer_token or "").encode()
        if not expected or not secrets.compare_digest(credential.encode(), expected):
            raise HTTPException(status_code=401, detail="未授权")
        request.state.auth_user = None
        return None

    # jwt 模式
    payload = _decode_token(credential)
    user = db.get(User, str(payload.get("sub")))
    if user is None or user.disabled:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用")
    request.state.auth_user = user
    return user


def get_request_user(request: Request) -> User | None:
    """业务处理器取认证身份（none/token 模式为 None，走兼容回退）。"""
    return getattr(request.state, "auth_user", None)


def require_roles(*roles: str):
    """角色校验工厂：仅 jwt 模式生效（none/token 无角色体系，维持现状）。"""

    async def checker(request: Request) -> None:
        if get_settings().auth_mode != "jwt":
            return
        user = get_request_user(request)
        if user is None:
            raise HTTPException(status_code=403, detail="此操作需要登录用户")
        if roles and user.role not in roles:
            raise HTTPException(status_code=403, detail=f"需要角色：{'/'.join(roles)}")

    return checker


# ---------- 上传文件签名 URL（WP2.3） ----------


def _secret_bytes() -> bytes:
    return get_settings().auth_jwt_secret.encode("utf-8")


def sign_upload_url(path: str) -> str:
    """给 /uploads 相对路径生成短期签名（exp + HMAC）。"""
    if get_settings().auth_mode == "none":
        return path
    exp = int(time.time()) + get_settings().upload_url_ttl_minutes * 60
    sig = hmac.new(_secret_bytes(), f"upload|{path}|{exp}".encode(), hashlib.sha256).hexdigest()
    return f"{path}?exp={exp}&sig={sig}"


def verify_upload_signature(path: str, exp: str | None, sig: str | None) -> None:
    """校验签名 URL；失败抛 401/410。仅 auth 模式下启用。"""
    if get_settings().auth_mode == "none":
        return
    if not exp or not sig:
        raise HTTPException(status_code=401, detail="缺少文件访问签名")
    try:
        exp_value = int(exp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="签名格式无效") from exc
    if exp_value < int(time.time()):
        raise HTTPException(status_code=410, detail="文件访问链接已过期，请刷新页面")
    expected = hmac.new(
        _secret_bytes(), f"upload|{path}|{exp}".encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401, detail="文件访问签名无效")


CurrentUser = Annotated[User | None, Depends(get_request_user)]
