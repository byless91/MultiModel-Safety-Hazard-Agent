"""Shared provider contracts, input models and typed errors."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProviderError(Exception):
    """Base error raised by model providers."""


class ModelTimeoutError(ProviderError):
    """Model call exceeded the configured timeout."""


class ModelUnavailableError(ProviderError):
    """Model endpoint rejected the call or the transport failed."""


@dataclass
class ImageInput:
    filename: str
    path: Path
    mime_type: str | None = None


class BaseProvider:
    name = "base"
    family = ""
    vision_model = ""
    text_model = ""
    embedding_model = ""

    def analyze(
        self,
        images: list[ImageInput],
        text: str,
        *,
        ocr_texts: list[str] | None = None,
        rag_evidence: list[str] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def complete(self, system: str, user: str) -> dict[str, Any]:
        raise NotImplementedError

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def compare(
        self,
        originals: list[ImageInput],
        rectifications: list[ImageInput],
        note: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError

    def describe(self) -> dict[str, str]:
        """Public metadata, safe to expose through the API."""
        return {
            "name": self.name,
            "family": self.family,
            "vision_model": self.vision_model,
            "text_model": self.text_model,
            "embedding_model": self.embedding_model,
        }
