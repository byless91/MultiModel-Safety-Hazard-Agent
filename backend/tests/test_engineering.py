"""P2 engineering checks: secret masking and upload filename hardening."""

import pytest
from fastapi import HTTPException

from app.api.routes import _safe_filename
from app.core.logging import SecretMaskingFormatter, mask_secrets


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
