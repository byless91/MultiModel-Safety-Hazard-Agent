"""Unit tests for PDF/Word to Markdown conversion used by the knowledge base."""

import asyncio
import sys

import pytest

from app.services.document_converter import (
    CONVERTIBLE_SUFFIXES,
    LEGACY_SUFFIX_HINTS,
    PLAIN_SUFFIXES,
    SUPPORTED_SUFFIXES,
    ConversionError,
    convert_to_markdown,
)


def test_supported_suffix_sets():
    assert PLAIN_SUFFIXES == {".txt", ".md", ".markdown"}
    assert CONVERTIBLE_SUFFIXES == {".pdf", ".docx"}
    assert SUPPORTED_SUFFIXES == {".txt", ".md", ".markdown", ".pdf", ".docx"}
    assert ".doc" not in SUPPORTED_SUFFIXES
    assert ".doc" in LEGACY_SUFFIX_HINTS


def test_convert_pdf_extracts_text(tmp_path, make_pdf):
    path = tmp_path / "law.pdf"
    path.write_bytes(
        make_pdf("Article 28: escape routes must stay unobstructed.")
    )
    text = asyncio.run(convert_to_markdown(path))
    assert "Article 28" in text
    assert "escape routes" in text


def test_convert_docx_extracts_chinese(tmp_path, make_docx):
    path = tmp_path / "law.docx"
    path.write_bytes(
        make_docx("第二十八条 任何单位、个人不得占用、堵塞、封闭疏散通道、安全出口。")
    )
    text = asyncio.run(convert_to_markdown(path))
    assert "第二十八条" in text
    assert "疏散通道" in text


def test_blank_document_raises_actionable_error(tmp_path, make_docx):
    path = tmp_path / "empty.docx"
    path.write_bytes(make_docx(""))
    with pytest.raises(ConversionError) as excinfo:
        asyncio.run(convert_to_markdown(path))
    assert "没有从文件里提取到文字" in str(excinfo.value)
    assert "扫描件" in str(excinfo.value)


def test_binary_garbage_raises_conversion_error(tmp_path):
    # MarkItDown falls back to content sniffing, so a text payload named .pdf is
    # still ingested as text. Genuinely unsupported binary must fail loudly.
    path = tmp_path / "broken.pdf"
    path.write_bytes(bytes(range(256)) * 40)
    with pytest.raises(ConversionError) as excinfo:
        asyncio.run(convert_to_markdown(path))
    assert "文件解析失败" in str(excinfo.value)


def test_text_payload_named_pdf_is_ingested_as_text(tmp_path):
    path = tmp_path / "disguised.pdf"
    path.write_bytes(b"Article 28: keep escape routes clear.")
    text = asyncio.run(convert_to_markdown(path))
    assert "escape routes" in text


def test_output_length_cap_is_enforced(tmp_path, make_docx):
    path = tmp_path / "long.docx"
    path.write_bytes(make_docx("第二十八条 " * 200))
    with pytest.raises(ConversionError) as excinfo:
        asyncio.run(convert_to_markdown(path, max_chars=100))
    assert "过长" in str(excinfo.value)


def test_missing_markitdown_gives_clear_error(tmp_path, make_docx, monkeypatch):
    path = tmp_path / "law.docx"
    path.write_bytes(make_docx("第二十八条 禁止占用疏散通道。"))
    monkeypatch.setitem(sys.modules, "markitdown", None)
    with pytest.raises(ConversionError) as excinfo:
        asyncio.run(convert_to_markdown(path))
    assert "未安装文档转换组件" in str(excinfo.value)


def test_conversion_timeout_raises_actionable_error(tmp_path, make_pdf, monkeypatch):
    path = tmp_path / "slow.pdf"
    path.write_bytes(make_pdf("slow"))

    def _hang(_path):
        import time

        time.sleep(2)
        return "too late"

    monkeypatch.setattr(
        "app.services.document_converter._convert_sync", _hang
    )
    with pytest.raises(ConversionError) as excinfo:
        asyncio.run(convert_to_markdown(path, timeout=0.1))
    assert "超时" in str(excinfo.value)
