"""slowapi 限流器（B4/WP2.4）。

默认关闭（RATE_LIMIT_ENABLED=false，避免测试与开发误伤），生产开启。
限流键：登录用户按 user id，匿名按客户端 IP。
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings
from app.core.security import get_request_user


def _rate_key(request) -> str:
    user = get_request_user(request)
    if user is not None:
        return f"user:{user.id}"
    return f"ip:{get_remote_address(request)}"


class _DynamicLimiter(Limiter):
    """slowapi 的 enabled 只接受静态值；用属性让开关实时跟随 Settings。"""

    @property
    def enabled(self) -> bool:
        return get_settings().rate_limit_enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:  # 构造器赋值，忽略
        pass


limiter = _DynamicLimiter(key_func=_rate_key)
