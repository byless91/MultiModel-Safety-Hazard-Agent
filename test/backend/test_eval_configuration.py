"""R6/T15: isolate experimental variables while preserving deployment inputs."""

import json

import pytest
from app.core.config import get_settings
from app.eval.evaluation import (
    build_variant_settings,
    configuration_summary,
    evaluation_mode,
    pick_variant,
)


@pytest.mark.parametrize("name", ["qwen", "glm", "ensemble", "plus_risk", "plus_rag", "full"])
def test_variants_preserve_all_non_experimental_fields(tmp_path, monkeypatch, name):
    base = get_settings().model_copy(update={
        "vision_model": "custom-model", "zhipu_vision_model": "custom-glm",
        "knowledge_dir": tmp_path / "knowledge", "faiss_index_dir": tmp_path / "index",
        "dashscope_base_url": "https://example.invalid/custom/v1", "model_timeout": 13.5,
        "retrieval_top_k": 2, "conf_weights": "0.1,0.2,0.3,0.4", "reranker_enabled": False,
        "dashscope_api_key": "qwen-secret", "zhipu_api_key": "glm-secret",
    })
    monkeypatch.setenv("VISION_MODEL", "environment-should-not-override-base")
    settings = build_variant_settings(base, pick_variant(name), provider_mode="auto")
    changes = {"provider_mode", "enable_risk_engine", "enable_evidence_rag", "refine_with_evidence",
               "mock_demo_boost", "dashscope_api_key", "zhipu_api_key"}
    for field in type(base).model_fields:
        if field not in changes:
            assert getattr(settings, field) == getattr(base, field), field
    assert settings.dashscope_api_key == ("" if name == "glm" else "qwen-secret")
    assert settings.zhipu_api_key == ("" if name == "qwen" else "glm-secret")
    assert base.dashscope_api_key == "qwen-secret"


def test_mock_clears_model_credentials_and_demo_boost():
    base = get_settings().model_copy(update={"dashscope_api_key": "secret", "zhipu_api_key": "other",
                                            "mock_demo_boost": True})
    settings = build_variant_settings(base, pick_variant("full"), provider_mode="mock")
    assert not settings.dashscope_api_key and not settings.zhipu_api_key
    assert not settings.mock_demo_boost
    assert evaluation_mode(settings) == "mock"


def test_auto_without_keys_reports_actual_mock():
    settings = build_variant_settings(get_settings().model_copy(update={
        "dashscope_api_key": "", "zhipu_api_key": "",
    }), pick_variant("full"), provider_mode="auto")
    assert settings.provider_mode == "auto"
    assert evaluation_mode(settings) == "mock"


def test_configuration_uses_allowlist_and_redacts_url_credentials():
    settings = get_settings().model_copy(update={
        "dashscope_api_key": "paid-secret", "auth_jwt_secret": "jwt-secret",
        "database_url": "postgres://person:db-secret@localhost/private",
        "dashscope_base_url": "https://person:url-secret@example.invalid/v1?api_key=query-secret#fragment",
    })
    summary = configuration_summary(settings)
    encoded = json.dumps(summary)
    for secret in ("paid-secret", "jwt-secret", "db-secret", "url-secret", "query-secret"):
        assert secret not in encoded
    assert summary["dashscope_base_url"] == "https://example.invalid/v1"
