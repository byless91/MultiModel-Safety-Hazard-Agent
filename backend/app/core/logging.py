"""Process-wide logging with secret masking."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.core.config import get_settings

_SENSITIVE_PATTERNS = (
    re.compile(
        r"(?i)(\b(?:api[_-]?key|secret|token|password)\b\s*[:=]?\s*)"
        r"([A-Za-z0-9._~+/\-]{6,})"
    ),
    re.compile(r"(?i)(\bBearer\s+)([A-Za-z0-9._~+/\-]{6,})"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
)


def mask_secrets(text: str) -> str:
    """Replace likely credential material before it reaches logs."""
    if not text:
        return text
    masked = _SENSITIVE_PATTERNS[0].sub(r"\1[REDACTED]", text)
    masked = _SENSITIVE_PATTERNS[1].sub(r"\1[REDACTED]", masked)
    masked = _SENSITIVE_PATTERNS[2].sub("[REDACTED]", masked)
    return masked


class SecretMaskingFormatter(logging.Formatter):
    """Formatter that masks secrets in every record message/args."""

    def format(self, record: logging.LogRecord) -> str:
        original = record.getMessage()
        masked = mask_secrets(original)
        record = logging.LogRecord(
            record.name,
            record.levelno,
            record.pathname,
            record.lineno,
            masked,
            None,
            record.exc_info,
            record.funcName,
            record.stack_info,
        )
        return super().format(record)


class SecretMaskingFilter(logging.Filter):
    """Rewrite log records before any handler formats them."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            masked = mask_secrets(record.getMessage())
        except Exception:
            return True
        record.msg = masked
        record.args = ()
        return True


def setup_logging() -> None:
    settings = get_settings()
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        stream = logging.StreamHandler()
        stream.setFormatter(
            SecretMaskingFormatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s"
            )
        )
        root.addHandler(stream)
        log_dir = Path(settings.upload_dir).parent / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
            file_handler.setFormatter(
                SecretMaskingFormatter(
                    "%(asctime)s %(levelname)s %(name)s: %(message)s"
                )
            )
            root.addHandler(file_handler)
        except OSError:
            pass
    for handler in root.handlers:
        if not any(
            isinstance(filter_item, SecretMaskingFilter)
            for filter_item in handler.filters
        ):
            handler.addFilter(SecretMaskingFilter())
