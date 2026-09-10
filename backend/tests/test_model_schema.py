import json

import pytest
from pydantic import ValidationError

from app.services.providers import (
    HazardFinding,
    MockProvider,
    normalize_analysis,
)
from app.services.providers import http as http_module


def test_legacy_flat_fields_are_preserved():
    raw = {
        "scene_summary": "楼道场景",
        "observations": ["堆物", "通道受阻"],
        "hazard_hints": ["占用疏散通道"],
        "keywords": ["纸箱"],
        "vision_confidence": 0.9,
    }
    analysis = normalize_analysis(raw, provider="mock", family="mock", model="mock")
    data = analysis.to_workflow_dict()
    assert data["scene_summary"] == "楼道场景"
    assert data["observations"] == ["堆物", "通道受阻"]
    assert data["hazard_hints"] == ["占用疏散通道"]
    assert data["hazards"] == []
    assert data["schema_valid"] is True
    assert data["rule"] == {}


def test_hazard_finding_validates_strict_ranges():
    with pytest.raises(ValidationError):
        HazardFinding(hazard_type="x", severity=9)
    with pytest.raises(ValidationError):
        HazardFinding(hazard_type="x", severity=2, confidence=1.5)
    with pytest.raises(ValidationError):
        HazardFinding(hazard_type="x", location={"image_id": "i", "bbox": [1, 2]})


def test_normalize_clamps_and_marks_warnings():
    raw = {
        "vision_confidence": 1.5,
        "llm_confidence": -0.2,
        "rule_score": 3,
        "hazards": [
            {
                "hazard_type": "fire_exit_blocked",
                "description": "通道被占",
                "severity": 9,
                "confidence": 2,
                "observed_facts": "不是数组",
                "location": {
                    "image_id": "image_01",
                    "bbox": [1, 2, 3, 4],
                    "location_text": "图片中部",
                },
            }
        ],
    }
    analysis = normalize_analysis(
        raw,
        provider="dashscope",
        family="qwen-vl",
        model="qwen-vl-plus",
    )
    assert analysis.vision_confidence == 1.0
    assert analysis.llm_confidence == 0.0
    assert analysis.rule_score == 0.0
    mock_analysis = normalize_analysis(
        raw,
        provider="mock",
        family="mock",
        model="mock-vision",
    )
    assert mock_analysis.rule_score == 1.0
    finding = analysis.hazards[0]
    assert finding.severity == 3
    assert finding.confidence == 1.0
    assert finding.observed_facts == ["不是数组"]
    assert finding.location is not None
    assert finding.location.bbox == [1.0, 2.0, 3.0, 4.0]
    assert analysis.validation_warnings
    assert analysis.to_workflow_dict()["schema_valid"] is False


def test_invalid_bbox_is_dropped_with_warning():
    raw = {
        "hazards": [
            {
                "hazard_type": "electrical",
                "location": {"image_id": "image_01", "bbox": [1, 2]},
            }
        ]
    }
    analysis = normalize_analysis(raw)
    finding = analysis.hazards[0]
    assert finding.location is not None
    assert finding.location.bbox is None
    assert finding.location.image_id == "image_01"
    assert any("bbox" in item for item in analysis.validation_warnings)


def test_real_provider_rule_and_rule_score_are_ignored():
    from app.services.providers.schemas import normalize_analysis

    raw = {
        "vision_confidence": 0.8,
        "hazard_hints": ["占用疏散通道"],
        "rule": {"category": "占用疏散通道", "level": 1},
        "rule_score": 1.0,
        "hazards": [{"hazard_type": "占用疏散通道", "severity": 1}],
    }
    real = normalize_analysis(
        raw,
        provider="qwen-vl",
        family="qwen-vl",
        model="qwen-vl-plus",
    )
    assert real.rule == {}
    assert real.rule_score == 0.0

    mock = normalize_analysis(
        raw,
        provider="mock",
        family="mock",
        model="mock-vision",
    )
    assert mock.rule == {"category": "占用疏散通道", "level": 1}
    assert mock.rule_score == 1.0


def test_mock_provider_returns_structured_analysis():
    data = MockProvider().analyze([], "小区楼道堆放纸箱杂物，堵塞疏散通道")
    assert data["model"] == "mock-vision"
    assert data["hazards"]
    finding = data["hazards"][0]
    assert finding["hazard_type"] == "占用疏散通道"
    assert finding["severity"] == 3
    assert finding["confidence"] > 0.8
    assert data["rule"]["level"] == 1
    assert data["schema_valid"] is True
    assert data["validation_warnings"] == []


def test_http_provider_returns_normalized_analysis(monkeypatch):
    provider = http_module.OpenAICompatibleProvider(
        base_url="http://fake",
        api_key="sk-test",
        vision_model="qwen-vl-plus",
        text_model="qwen-plus",
        embedding_model="text-embedding-v3",
        name="dashscope",
        family="qwen-vl",
    )

    def fake_post(path: str, payload: dict):
        content = json.dumps(
            {
                "scene_summary": "车间",
                "hazard_hints": ["电气线路隐患"],
                "hazards": [
                    {
                        "hazard_type": "electrical",
                        "severity": 3,
                        "confidence": 0.8,
                    }
                ],
            },
            ensure_ascii=False,
        )
        return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr(provider, "_post", fake_post)
    data = provider.analyze([], "配电箱破损")
    assert data["model"] == "qwen-vl-plus"
    assert data["scene_summary"] == "车间"
    assert data["hazards"][0]["severity"] == 3
    assert data["hazards"][0]["confidence"] == 0.8
    assert data["validation_warnings"] == []
