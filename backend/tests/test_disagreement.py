from app.services.ensemble import (
    StandardizedFinding,
    StandardizedModelResult,
    detect_disagreement,
)


def _model(
    family: str,
    findings: list[StandardizedFinding],
    status: str = "success",
) -> StandardizedModelResult:
    return StandardizedModelResult(
        provider=family,
        family=family,
        model=f"{family}-model",
        status=status,
        vision_confidence=0.9,
        findings=findings,
    )


def _finding(category: str, severity: int | None, facts=None, confidence=0.9) -> StandardizedFinding:
    return StandardizedFinding(
        finding_id=category,
        canonical_category=category,
        raw_hazard_type=category,
        severity=severity,
        confidence=confidence,
        observed_facts=facts or [],
    )


def test_identical_findings_agree():
    first = _model("qwen-vl", [_finding("占用疏散通道", 3)])
    second = _model("glm-v", [_finding("占用疏散通道", 3)])
    result = detect_disagreement([first, second], ensemble_mode="full")
    assert result.mode == "pair"
    assert result.agreement_available is True
    assert result.category_agreement is True
    assert result.severity_difference == 0
    assert result.agreement_score > 0.99
    assert result.need_human_review is False


def test_severity_gap_triggers_review():
    first = _model("qwen-vl", [_finding("占用疏散通道", 3)])
    second = _model("glm-v", [_finding("占用疏散通道", 1)])
    result = detect_disagreement([first, second], ensemble_mode="full")
    assert result.severity_difference == 2
    assert result.need_human_review is True
    assert any("等级差异过大" in reason for reason in result.reasons)


def test_one_level_severity_gap_triggers_review():
    first = _model("qwen-vl", [_finding("占用疏散通道", 3)])
    second = _model("glm-v", [_finding("占用疏散通道", 2)])
    result = detect_disagreement([first, second], ensemble_mode="full")
    assert result.severity_difference == 1
    assert result.need_human_review is True
    assert any("1 级分歧" in reason for reason in result.reasons)


def test_different_categories_conflict():
    first = _model("qwen-vl", [_finding("占用疏散通道", 2)])
    second = _model("glm-v", [_finding("电气线路隐患", 2)])
    result = detect_disagreement([first, second], ensemble_mode="full")
    assert result.category_agreement is False
    assert result.need_human_review is True
    assert any("类别不一致" in reason for reason in result.reasons)


def test_one_model_finds_nothing_is_critical_conflict():
    first = _model("qwen-vl", [_finding("占用疏散通道", 2)])
    second = _model("glm-v", [])
    result = detect_disagreement([first, second], ensemble_mode="full")
    assert result.critical_conflict is True
    assert result.need_human_review is True
    assert any("关键事实冲突" in reason for reason in result.reasons)


def test_negated_fact_conflict_detected():
    first = _model("qwen-vl", [_finding("消防器材失效", 2, ["未发现灭火器"])])
    second = _model("glm-v", [_finding("消防器材失效", 2, ["灭火器缺失"])])
    result = detect_disagreement([first, second], ensemble_mode="full")
    assert result.critical_conflict is True
    assert result.need_human_review is True
    assert any("关键事实描述" in reason for reason in result.reasons)


def test_duplicate_category_findings_are_all_compared():
    first = _model(
        "qwen-vl",
        [
            _finding("消防器材失效", 2, ["未发现灭火器"]),
            _finding("消防器材失效", 3, ["灭火器过期"]),
        ],
    )
    second = _model("glm-v", [_finding("消防器材失效", 2, ["灭火器缺失"])])
    result = detect_disagreement([first, second], ensemble_mode="full")
    assert result.critical_conflict is True
    assert result.need_human_review is True
    assert any("关键事实描述" in reason for reason in result.reasons)


def test_fallback_mode_always_requires_review():
    first = _model("qwen-vl", [_finding("占用疏散通道", 2)], status="failed")
    second = _model("mock", [], status="mock_fallback")
    result = detect_disagreement([first, second], ensemble_mode="fallback")
    assert result.mode == "fallback"
    assert result.need_human_review is True
    assert result.agreement_available is False


def test_single_configured_model_is_not_flagged_as_disagreement():
    mock_result = _model("mock", [_finding("占用疏散通道", 3)])
    result = detect_disagreement([mock_result], ensemble_mode="mock")
    assert result.mode == "single"
    assert result.need_human_review is False
    assert result.agreement_available is False


def test_partial_ensemble_requires_review():
    first = _model("qwen-vl", [_finding("占用疏散通道", 2)])
    second = _model("glm-v", [], status="failed")
    result = detect_disagreement([first, second], ensemble_mode="partial")
    assert result.mode == "partial"
    assert result.need_human_review is True


def test_workflow_state_contains_disagreement():
    from app.services.workflow import run_workflow

    state = run_workflow(description="小区楼道堆放纸箱杂物，堵塞疏散通道", images=[])
    assert state["disagreement"]["mode"] == "single"
    assert state["disagreement"]["need_human_review"] is False
