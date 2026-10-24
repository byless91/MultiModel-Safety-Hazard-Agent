"""Process-wide structured logging with secret masking and request correlation.

- 文件日志为 JSON（structlog ProcessorFormatter），控制台为人类可读格式
- 每条日志（原生 structlog 与 stdlib logging 记录）自动携带 request_id
- 渲染前对所有字符串值做密钥脱敏，覆盖两种来源的记录
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, MutableMapping
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog

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
    """Rewrite log records before any handler formats them.

    历史挂载点；structlog 化之后脱敏由 ``_mask_event_dict`` 在渲染前完成，
    本类保留供兼容与既有单测使用，不再自动挂到 handler 上。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            masked = mask_secrets(record.getMessage())
        except Exception:
            return True
        record.msg = masked
        record.args = ()
        return True


request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    """当前请求关联键；无请求上下文时返回 '-'。"""
    return request_id_var.get()


def _inject_request_id(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    event_dict.setdefault("request_id", request_id_var.get())
    return event_dict


def _mask_event_dict(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    """渲染前对事件字典中的全部字符串值脱敏（原生与 stdlib 记录均经过此处）。"""
    for key, value in list(event_dict.items()):
        if isinstance(value, str):
            event_dict[key] = mask_secrets(value)
    return event_dict


def _foreign_pre_chain() -> list[Any]:
    """stdlib logging 记录进入 structlog 渲染前的处理链。"""
    return [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _inject_request_id,
        structlog.processors.format_exc_info,
        _mask_event_dict,
    ]


def _configure_structlog() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _inject_request_id,
            structlog.processors.format_exc_info,
            _mask_event_dict,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def _json_formatter() -> structlog.stdlib.ProcessorFormatter:
    return structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        foreign_pre_chain=_foreign_pre_chain(),
    )


def _console_formatter() -> structlog.stdlib.ProcessorFormatter:
    return structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(),
        ],
        foreign_pre_chain=_foreign_pre_chain(),
    )


def setup_logging() -> None:
    settings = get_settings()
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        console = logging.StreamHandler()
        console.setFormatter(_console_formatter())
        root.addHandler(console)
        log_dir = Path(settings.upload_dir).parent / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_dir / "app.log",
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(_json_formatter())
            root.addHandler(file_handler)
        except OSError as exc:
            # 文件日志不可用时降级为仅控制台输出，但不能完全无声
            stream_handler = next(
                (h for h in root.handlers if isinstance(h, logging.StreamHandler)), None
            )
            if stream_handler is not None:
                stream_handler.emit(
                    logging.LogRecord(
                        "safety_hazard.logging",
                        logging.WARNING,
                        __file__,
                        0,
                        f"无法创建日志文件（{exc}），仅输出到控制台",
                        None,
                        None,
                    )
                )
    _configure_structlog()
