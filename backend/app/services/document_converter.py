"""Convert uploaded documents (PDF / Word) into Markdown for the knowledge base.

MarkItDown is the same converter the community ``markdownify-mcp`` server wraps;
calling it directly keeps this a single-process Python dependency instead of an
extra MCP runtime. Conversion is CPU/IO bound and runs in a worker thread so the
FastAPI event loop stays responsive.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

PLAIN_SUFFIXES = {".txt", ".md", ".markdown"}
CONVERTIBLE_SUFFIXES = {".pdf", ".docx"}
SUPPORTED_SUFFIXES = PLAIN_SUFFIXES | CONVERTIBLE_SUFFIXES

# Suffixes we recognise but deliberately do not accept, with a concrete fix.
LEGACY_SUFFIX_HINTS = {
    ".doc": "旧版 .doc 不受支持，请用 Word 另存为 .docx 后再上传",
    ".xls": "旧版 .xls 不受支持，请另存为 .xlsx 后再上传",
    ".ppt": "旧版 .ppt 不受支持，请另存为 .pptx 后再上传",
}

MAX_MARKDOWN_CHARS = 2_000_000
CONVERSION_TIMEOUT_SECONDS = 30.0


class ConversionError(RuntimeError):
    """Raised when a file cannot be turned into usable Markdown."""


def _convert_sync(path: Path) -> str:
    try:
        from markitdown import MarkItDown
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise ConversionError(
            "服务器未安装文档转换组件，暂时无法解析 PDF/Word，请改用 .md 或 .txt"
        ) from exc
    try:
        result = MarkItDown().convert(str(path))
    except Exception as exc:
        raise ConversionError(f"文件解析失败：{str(exc)[:160]}") from exc
    return str(getattr(result, "text_content", "") or "")


async def convert_to_markdown(
    path: Path,
    *,
    timeout: float = CONVERSION_TIMEOUT_SECONDS,
    max_chars: int = MAX_MARKDOWN_CHARS,
) -> str:
    """Return Markdown text for ``path``, or raise ``ConversionError``.

    The timeout is a soft guard: ``asyncio.wait_for`` stops waiting and frees the
    request, but a wedged parser thread cannot be force-killed in Python. The
    upload size limit is the primary protection.
    """
    try:
        text = await asyncio.wait_for(
            asyncio.to_thread(_convert_sync, path),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        raise ConversionError(
            f"文件解析超时（超过 {int(timeout)} 秒），请拆分或压缩后再上传"
        ) from exc
    text = text.strip()
    if not text:
        raise ConversionError(
            "没有从文件里提取到文字。若这是扫描件或图片版 PDF，请改用可复制文字的版本。"
        )
    if len(text) > max_chars:
        raise ConversionError(
            f"转换后文本过长（超过 {max_chars} 字符），请拆分后再上传"
        )
    return text
