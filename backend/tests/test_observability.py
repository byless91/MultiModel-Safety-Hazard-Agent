"""B1/WP3.3：可观测性基座——request id 关联、结构化日志脱敏与 /metrics 指标。"""

import json
import logging
import re

from fastapi.testclient import TestClient

from app.core.logging import _json_formatter, request_id_var
from app.main import app


def test_request_id_generated_and_echoed():
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    request_id = response.headers.get("X-Request-ID")
    assert request_id and re.fullmatch(r"[0-9a-f]{16}", request_id)


def test_incoming_request_id_is_honored():
    with TestClient(app) as client:
        response = client.get("/api/v1/health", headers={"X-Request-ID": "trace-abc-123"})
    assert response.headers.get("X-Request-ID") == "trace-abc-123"


def test_malformed_request_id_is_replaced():
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/health", headers={"X-Request-ID": "bad id with spaces!!"}
        )
    assert re.fullmatch(r"[0-9a-f]{16}", response.headers.get("X-Request-ID", ""))


def _render_via_json_formatter(record: logging.LogRecord) -> dict:
    return json.loads(_json_formatter().format(record))


def test_json_log_line_carries_request_id_and_masks_secrets():
    token = request_id_var.set("req-observability-1")
    try:
        record = logging.LogRecord(
            name="safety_hazard.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="calling provider api_key=sk-live-secret-abcdef123 done",
            args=(),
            exc_info=None,
        )
        payload = _render_via_json_formatter(record)
    finally:
        request_id_var.reset(token)
    assert payload["request_id"] == "req-observability-1"
    assert "sk-live-secret-abcdef123" not in payload["event"]
    assert "[REDACTED]" in payload["event"]
    assert "timestamp" in payload and "level" in payload


def test_metrics_endpoint_exposes_http_and_workflow_metrics():
    with TestClient(app) as client:
        # 触发一次完整研判（mock 模式），使业务指标有观测值
        created = client.post(
            "/api/v1/assessments", data={"description": "小区楼道堆放纸箱杂物，堵塞疏散通道"}
        )
        assert created.status_code == 201
        metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 200
    body = metrics_response.text
    # HTTP 层指标（instrumentator）与业务指标（workflow / model）均应出现
    assert "http_request_duration_seconds" in body or "http_request" in body
    assert "safety_hazard_workflow_duration_seconds" in body
    assert "safety_hazard_workflow_total" in body
    assert "safety_hazard_model_requests_total" in body
    assert "safety_hazard_workflow_total{" in body  # 已按状态标签记录
