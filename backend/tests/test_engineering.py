"""P2 engineering checks: secret masking, upload filename hardening, and B0 silent-failure surfacing."""

import logging
from logging.handlers import RotatingFileHandler

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.routes import _safe_filename
from app.core.logging import SecretMaskingFormatter, mask_secrets
from app.main import app


def test_mask_secrets_hides_keys_tokens_passwords():
    sample = (
        "Authorization: Bearer sk-abc123XYZsecret "
        "api_key=sk-live-key-abcdef123456 "
        "password=supersecret "
        "DASHSCOPE_API_KEY=sk-dash-key"
    )
    masked = mask_secrets(sample)
    assert "sk-abc123XYZsecret" not in masked
    assert "sk-live-key-abcdef123456" not in masked
    assert "supersecret" not in masked
    assert "sk-dash-key" not in masked
    assert masked.count("[REDACTED]") >= 2


def test_mask_secrets_preserves_plain_text():
    text = "normal info 消防法第三十条规定"
    assert mask_secrets(text) == text


def test_mask_secrets_handles_exceptions_and_errors():
    message = "HTTP 401: {'error': {'message': 'Invalid API key sk-invalid-test-0001'}}"
    masked = mask_secrets(message)
    assert "sk-invalid-test-0001" not in masked


def test_log_formatter_masks_record_message():
    import logging

    formatter = SecretMaskingFormatter("%(message)s")
    record = logging.LogRecord(
        name="test",
        level=20,
        pathname=__file__,
        lineno=1,
        msg="key sk-secret-123 msg",
        args=(),
        exc_info=None,
    )
    record = formatter.format(record)
    assert "sk-secret-123" not in record
    assert "[REDACTED]" in record


def test_safe_filename_rejects_path_traversal():
    for bad in ("../../etc/passwd", "..\\etc\\passwd", "a/../b.png", "C:\\windows\\evil.png"):
        with pytest.raises(HTTPException) as excinfo:
            _safe_filename(bad, allowed_suffixes={".png"}, default="image.png")
        assert excinfo.value.status_code == 400


def test_safe_filename_rejects_bad_extension_and_control_chars():
    with pytest.raises(HTTPException):
        _safe_filename("payload.exe", allowed_suffixes={".png"}, default="image.png")
    with pytest.raises(HTTPException):
        _safe_filename("bad\u0000name.png", allowed_suffixes={".png"}, default="image.png")


def test_safe_filename_accepts_normal_upload():
    name, suffix = _safe_filename("site_photo.JPG", allowed_suffixes={".jpg"}, default="image.jpg")
    assert name == "site_photo.JPG"
    assert suffix == ".jpg"


def test_file_logging_uses_rotating_handler():
    """日志文件必须轮转，否则长期运行会写爆磁盘。

    pytest 的 logging 插件会摘走 root handlers，因此在干净的 root 上重新执行
    setup_logging 验证其产物，断言后还原现场。
    """
    from app.core.logging import setup_logging

    root = logging.getLogger()
    saved = root.handlers[:]
    root.handlers.clear()
    try:
        setup_logging()
        file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
        assert file_handlers, "未发现 RotatingFileHandler，日志文件无轮转"
        assert all(h.backupCount > 0 for h in file_handlers)
    finally:
        added = [h for h in root.handlers if h not in saved]
        root.handlers[:] = saved
        for handler in added:
            handler.close()


def test_delete_document_rebuild_failure_is_logged(monkeypatch, caplog):
    """删除后的索引重建失败可以不改变 204 响应，但绝不能静默无日志。"""
    from app.api import routes as routes_module

    def broken_rebuild(db=None):
        raise RuntimeError("reindex boom")

    monkeypatch.setattr(routes_module, "rebuild_knowledge", broken_rebuild)
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/knowledge/documents",
            data={"title": "待删除法规"},
            files=[("file", ("law.md", "第四十一条 建立隐患排查治理制度。".encode(), "text/markdown"))],
        )
        assert created.status_code == 201
        doc_id = created.json()["id"]
        with caplog.at_level(logging.ERROR, logger="safety_hazard.api"):
            deleted = client.delete(f"/api/v1/knowledge/documents/{doc_id}")
    assert deleted.status_code == 204
    assert any("重建失败" in record.message for record in caplog.records)


def test_analyze_node_silent_degradation_is_logged(monkeypatch, caplog):
    """模型故障降级 Mock 必须留下 warning 日志，禁止无声降级。"""
    from app.core.config import get_settings
    from app.services import langgraph_flow, workflow_nodes
    from app.services.providers import MockProvider
    from app.services.rag import get_rag

    def broken_analysis(*args, **kwargs):
        raise RuntimeError("vision provider timeout")

    monkeypatch.setattr(workflow_nodes, "run_parallel_analysis", broken_analysis)
    settings = get_settings()
    rag = get_rag()
    provider = MockProvider()
    with caplog.at_level(logging.WARNING, logger="safety_hazard.workflow"):
        state = langgraph_flow.node_analyze(
            {
                "description": "楼道堆放纸箱杂物",
                "images": [],
                "settings": settings,
                "provider": provider,
                "providers": [provider],
                "rag": rag,
            }
        )
    assert state["multi_model"]["ensemble_mode"] == "fallback"
    assert any("降级" in record.message for record in caplog.records)


def test_analyze_node_programming_error_is_not_masked(monkeypatch):
    """编程错误（如 TypeError）不得被 Mock 兜底掩盖，必须显式抛出。"""
    from app.core.config import get_settings
    from app.services import langgraph_flow, workflow_nodes
    from app.services.providers import MockProvider
    from app.services.rag import get_rag

    def broken_analysis(*args, **kwargs):
        raise TypeError("bad downstream call")

    monkeypatch.setattr(workflow_nodes, "run_parallel_analysis", broken_analysis)
    with pytest.raises(TypeError):
        langgraph_flow.node_analyze(
            {
                "description": "楼道堆物",
                "images": [],
                "settings": get_settings(),
                "provider": MockProvider(),
                "rag": get_rag(),
            }
        )
