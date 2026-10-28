"""One process-wide gate at the real HTTP boundary, shared by all providers."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from app.core.config import get_settings


class HTTPConcurrencyGate:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active = 0
        self._local = threading.local()

    @contextmanager
    def slot(self) -> Iterator[None]:
        from app.services.providers.base import ModelCapacityError, ModelUnavailableError

        if getattr(self._local, "held", False):
            raise ModelUnavailableError("模型 HTTP 入口不支持递归调用，已拒绝以避免嵌套等待")
        settings = get_settings()
        with self._condition:
            available = self._condition.wait_for(
                lambda: self._active < settings.max_concurrent_llm_calls,
                timeout=settings.llm_queue_timeout_seconds,
            )
            if not available:
                raise ModelCapacityError("模型服务繁忙，等待并发名额超时；本次未发送 HTTP 请求")
            self._active += 1
            self._local.held = True
        try:
            yield
        finally:
            with self._condition:
                self._active -= 1
                self._local.held = False
                self._condition.notify_all()


http_gate = HTTPConcurrencyGate()
