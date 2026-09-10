"""Provider layer for vision, text and embedding model access.

Existing imports such as ``from app.services.providers import get_provider`` keep
working. ``get_provider`` returns the primary provider; ``get_providers``
returns every configured provider so the ensemble layer can invoke them in
parallel in a later phase. This list is never used as if it were an ensemble
already.
"""

from app.core.config import get_settings
from app.services.providers.base import (
    BaseProvider,
    ImageInput,
    ModelTimeoutError,
    ModelUnavailableError,
    ProviderError,
)
from app.services.providers.factory import build_provider, build_providers
from app.services.providers.http import (
    COMPARE_PROMPT,
    VISION_PROMPT,
    OpenAICompatibleProvider,
)
from app.services.providers.mock import MockProvider, RULE_TEMPLATES, hash_embed
from app.services.providers.qwen import QwenProvider
from app.services.providers.schemas import (
    HazardFinding,
    HazardLocation,
    ModelAnalysis,
    normalize_analysis,
)
from app.services.providers.zhipu import ZhipuProvider

__all__ = [
    "BaseProvider",
    "ImageInput",
    "ModelTimeoutError",
    "ModelUnavailableError",
    "ProviderError",
    "OpenAICompatibleProvider",
    "QwenProvider",
    "ZhipuProvider",
    "MockProvider",
    "RULE_TEMPLATES",
    "hash_embed",
    "HazardFinding",
    "HazardLocation",
    "ModelAnalysis",
    "normalize_analysis",
    "VISION_PROMPT",
    "COMPARE_PROMPT",
    "build_provider",
    "build_providers",
    "get_provider",
    "get_providers",
    "reset_provider",
]

_providers: list[BaseProvider] | None = None


def get_providers() -> list[BaseProvider]:
    global _providers
    if _providers is None:
        _providers = build_providers(get_settings())
    return _providers


def get_provider() -> BaseProvider:
    return get_providers()[0]


def reset_provider() -> None:
    global _providers
    _providers = None
