"""Provider factory independent from concrete workflow code."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.services.providers.base import BaseProvider
from app.services.providers.mock import MockProvider
from app.services.providers.qwen import QwenProvider
from app.services.providers.zhipu import ZhipuProvider


def build_providers(settings: Settings) -> list[BaseProvider]:
    """Return every configured model provider, or Mock when none is usable."""
    if settings.provider_mode == "mock":
        return [MockProvider()]
    providers: list[BaseProvider] = []
    if settings.dashscope_api_key:
        providers.append(
            QwenProvider(
                api_key=settings.dashscope_api_key,
                base_url=settings.dashscope_base_url,
                vision_model=settings.vision_model,
                text_model=settings.text_model,
                embedding_model=settings.embedding_model,
                timeout=settings.model_timeout,
                max_retries=settings.model_max_retries,
                retry_backoff=settings.model_retry_backoff,
            )
        )
    if settings.zhipu_api_key:
        providers.append(
            ZhipuProvider(
                api_key=settings.zhipu_api_key,
                base_url=settings.zhipu_base_url,
                vision_model=settings.zhipu_vision_model,
                text_model=settings.zhipu_text_model,
                embedding_model=settings.zhipu_embedding_model,
                timeout=settings.model_timeout,
                max_retries=settings.model_max_retries,
                retry_backoff=settings.model_retry_backoff,
            )
        )
    return providers or [MockProvider()]


def build_provider(settings: Settings) -> BaseProvider:
    """Backward-compatible primary provider accessor."""
    return build_providers(settings)[0]
