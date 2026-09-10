from app.services.ensemble import (
    StandardizedModelResult,
    canonicalize_hazard_type,
    standardize_analysis,
    standardize_model_runs,
)


def test_synonyms_map_to_the_same_canonical_category():
    assert canonicalize_hazard_type("消防通道堵塞") == "占用疏散通道"
    assert canonicalize_hazard_type("fire_exit_blocked") == "占用疏散通道"
    assert canonicalize_hazard_type("灭火器失效") == "消防器材失效"
    assert canonicalize_hazard_type("完全未知类型XYZ") is None


def test_two_models_converge_to_comparable_findings():
    model_a = standardize_analysis(
        {
            "hazards": [
                {
                    "hazard_type": "消防通道堵塞",
                    "description": "出口被货物堵住",
                    "severity": 3,
                    "confidence": 0.9,
                    "observed_facts": ["安全出口被货物堵住"],
                }
            ]
        },
        provider="dashscope",
        family="qwen-vl",
        model="qwen-vl-plus",
        status="success",
    )
    model_b = standardize_analysis(
        {
            "hazards": [
                {
                    "hazard_type": "占用疏散通道",
                    "description": "安全出口阻塞",
                    "severity": 2,
                    "confidence": 0.8,
                    "observed_facts": ["出口前有货物"],
                }
            ]
        },
        provider="zhipu",
        family="glm-v",
        model="glm-4v-flash",
        status="success",
    )
    assert model_a.findings[0].canonical_category == "占用疏散通道"
    assert model_b.findings[0].canonical_category == "占用疏散通道"
    assert model_a.findings[0].raw_hazard_type == "消防通道堵塞"
    assert model_b.findings[0].raw_hazard_type == "占用疏散通道"
    assert model_a.findings[0].finding_id == model_b.findings[0].finding_id


def test_hint_only_output_creates_derived_finding_without_severity():
    result = standardize_analysis(
        {
            "vision_confidence": 0.72,
            "hazard_hints": ["灭火器过期"],
            "observations": ["压力表指针在红区"],
        },
        provider="dashscope",
        family="qwen-vl",
        model="qwen-vl-plus",
        status="success",
    )
    assert result.findings
    finding = result.findings[0]
    assert finding.canonical_category == "消防器材失效"
    assert finding.severity is None
    assert finding.source == "hint_derived"
    assert finding.observed_facts == ["压力表指针在红区"]


def test_dedupe_keeps_distinct_hazards_with_different_locations():
    result = standardize_analysis(
        {
            "hazards": [
                {
                    "hazard_type": "占用疏散通道",
                    "severity": 2,
                    "confidence": 0.8,
                    "observed_facts": ["楼道左侧纸箱"],
                    "location": {"image_id": "img-1", "bbox": [0, 0, 10, 10]},
                },
                {
                    "hazard_type": "占用疏散通道",
                    "severity": 3,
                    "confidence": 0.9,
                    "observed_facts": ["楼道右侧纸箱"],
                    "location": {"image_id": "img-1", "bbox": [20, 20, 30, 30]},
                },
            ]
        },
        provider="dashscope",
        family="qwen-vl",
        model="qwen-vl-plus",
        status="success",
    )
    assert len(result.findings) == 2
    bboxes = [tuple(finding.location["bbox"]) for finding in result.findings]
    assert len(set(bboxes)) == 2


def test_failed_model_produces_empty_standardized_result():
    result = standardize_model_runs(
        [
            {
                "provider": "zhipu",
                "family": "glm-v",
                "model": "glm-4v-flash",
                "status": "failed",
                "analysis": None,
            }
        ]
    )
    assert result[0].status == "failed"
    assert result[0].findings == []
    assert isinstance(result[0], StandardizedModelResult)


def test_severity_out_of_range_is_clamped():
    result = standardize_analysis(
        {
            "hazards": [
                {
                    "hazard_type": "明火",
                    "severity": 9,
                    "confidence": 0.8,
                }
            ]
        },
        provider="mock",
        family="mock",
        model="mock-vision",
        status="success",
    )
    assert result.findings[0].severity == 3


def test_workflow_state_keeps_standardized_results():
    from app.services.workflow import run_workflow

    state = run_workflow(description="小区楼道堆放纸箱杂物，堵塞疏散通道", images=[])
    assert state["standardized_results"]
    standardized = state["standardized_results"][0]
    assert standardized["status"] == "success"
    assert standardized["findings"][0]["canonical_category"] == "占用疏散通道"
