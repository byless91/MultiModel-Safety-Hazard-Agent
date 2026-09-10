from app.services.ensemble import (
    StandardizedFinding,
    StandardizedModelResult,
    detect_disagreement,
    judge_ensemble,
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


def _finding(
    category: str,
    severity: int | None,
    facts=None,
    confidence: float = 0.9,
    location: dict | None = None,
) -> StandardizedFinding:
    return StandardizedFinding(
        finding_id=category,
        canonical_category=category,
        raw_hazard_type=category,
        severity=severity,
        confidence=confidence,
        observed_facts=facts or [],
        location=location,
    )


def test_judge_merges_agreement_into_final_finding():
    first = _model("qwen-vl", [_finding("占用疏散通道", 3, ["通道有纸箱"])])
    second = _model("glm-v", [_finding("占用疏散通道", 3, ["纸箱占用通道"])])
    disagreement = detect_disagreement([first, second], ensemble_mode="full")
    result = judge_ensemble([first, second], disagreement)
    assert result.mode == "pair"
    assert len(result.final_findings) == 1
    finding = result.final_findings[0]
    assert finding.category == "占用疏散通道"
    assert finding.final_severity == 3
    assert finding.model_support == ["qwen-vl", "glm-v"]
    assert finding.source == "ensemble"
    assert finding.evidence_status == "pending"
    assert result.confidence > 0.9
    assert result.need_human_review is False
    assert "占用疏散通道" in result.decision_summary


def test_judge_takes_conservative_max_severity_on_conflict():
    first = _model("qwen-vl", [_finding("占用疏散通道", 3)])
    second = _model("glm-v", [_finding("占用疏散通道", 1)])
    disagreement = detect_disagreement([first, second], ensemble_mode="full")
    result = judge_ensemble([first, second], disagreement)
    assert result.final_findings[0].final_severity == 3
    assert result.need_human_review is True
    assert any("等级差异过大" in reason for reason in result.review_reasons)


def test_judge_keeps_both_categories_on_disagreement():
    first = _model("qwen-vl", [_finding("占用疏散通道", 2)])
    second = _model("glm-v", [_finding("电气线路隐患", 2)])
    disagreement = detect_disagreement([first, second], ensemble_mode="full")
    result = judge_ensemble([first, second], disagreement)
    assert [item.category for item in result.final_findings] == ["占用疏散通道", "电气线路隐患"]
    assert result.need_human_review is True


def test_judge_keeps_finding_when_only_one_model_detects():
    first = _model("qwen-vl", [_finding("占用疏散通道", 2)])
    second = _model("glm-v", [])
    disagreement = detect_disagreement([first, second], ensemble_mode="full")
    result = judge_ensemble([first, second], disagreement)
    assert len(result.final_findings) == 1
    assert result.final_findings[0].model_support == ["qwen-vl"]
    assert result.need_human_review is True


def test_fallback_judge_keeps_mock_finding_but_requires_review():
    fallback = _model("mock", [_finding("占用疏散通道", 3)], status="mock_fallback")
    failed = _model("qwen-vl", [], status="failed")
    disagreement = detect_disagreement([failed, fallback], ensemble_mode="fallback")
    result = judge_ensemble([failed, fallback], disagreement)
    assert result.mode == "fallback"
    assert result.need_human_review is True
    assert result.final_findings[0].source == "mock_fallback"
    assert "降级为 Mock" in result.decision_summary


def test_no_findings_requires_human_confirmation():
    first = _model("qwen-vl", [])
    second = _model("glm-v", [])
    disagreement = detect_disagreement([first, second], ensemble_mode="full")
    result = judge_ensemble([first, second], disagreement)
    assert result.final_findings == []
    assert result.need_human_review is True
    assert any("未检出明显隐患" in reason for reason in result.review_reasons)


def test_workflow_state_contains_ensemble_judge():
    from app.services.workflow import run_workflow

    state = run_workflow(description="小区楼道堆放纸箱杂物，堵塞疏散通道", images=[])
    judge = state["ensemble_judge"]
    assert judge["mode"] == "single"
    assert judge["final_findings"][0]["category"] == "占用疏散通道"
    assert judge["need_human_review"] is True
    assert any("风险规则引擎" in reason for reason in judge["review_reasons"])
    assert judge["version"] == "v1"


def test_judge_consumes_risk_and_evidence_in_decision():
    first = _model("qwen-vl", [_finding("占用疏散通道", 3, ["疏散通道被纸箱堵塞"])])
    second = _model("glm-v", [_finding("占用疏散通道", 3, ["疏散通道被纸箱堵塞"])])
    disagreement = detect_disagreement([first, second], ensemble_mode="full")
    risk = {
        "risk_score": 82,
        "risk_level": "high",
        "rule_version": "risk-engine-v1",
        "review_suggestion": True,
    }
    evidence = [
        {
            "id": "law-1",
            "source": "官方",
            "article": "第二十八条",
            "text": "不得占用、堵塞、封闭疏散通道、安全出口",
            "score": 0.8,
        }
    ]
    result = judge_ensemble(
        [first, second],
        disagreement,
        risk_result=risk,
        evidence=evidence,
    )
    assert result.risk_score == 82
    assert result.risk_level == "high"
    finding = result.final_findings[0]
    assert finding.risk_score == 82
    assert finding.evidence_status == "supported"
    assert finding.support_score is not None
    assert result.need_human_review is True
    assert any("高风险" in reason for reason in result.review_reasons)


def test_final_finding_keeps_location_bbox():
    first = _model(
        "qwen-vl",
        [
            _finding(
                "占用疏散通道",
                3,
                ["通道有纸箱"],
                location={
                    "image_id": "img-1",
                    "bbox": [0.1, 0.2, 0.3, 0.4],
                    "location_text": "楼道中部",
                },
            )
        ],
    )
    second = _model(
        "glm-v",
        [
            _finding(
                "占用疏散通道",
                3,
                ["纸箱占用通道"],
                location={"image_id": "img-1", "bbox": [0.1, 0.2, 0.3, 0.4]},
            )
        ],
    )
    disagreement = detect_disagreement([first, second], ensemble_mode="full")
    result = judge_ensemble([first, second], disagreement)
    assert result.final_findings[0].locations
    assert result.final_findings[0].locations[0]["bbox"] == [0.1, 0.2, 0.3, 0.4]


def test_final_finding_preserves_per_model_trace():
    first = _model("qwen-vl", [_finding("占用疏散通道", 3, ["通道有纸箱"])])
    second = _model("glm-v", [_finding("占用疏散通道", 2, ["纸箱占用通道"])])
    disagreement = detect_disagreement([first, second], ensemble_mode="full")
    result = judge_ensemble([first, second], disagreement)
    finding = result.final_findings[0]
    assert len(finding.model_findings) == 2
    assert {item["family"] for item in finding.model_findings} == {"qwen-vl", "glm-v"}
    assert all(item["observed_facts"] for item in finding.model_findings)


def test_same_category_different_locations_stay_separate():
    first = _model(
        "qwen-vl",
        [
            _finding(
                "占用疏散通道",
                2,
                ["楼道左侧纸箱"],
                location={"image_id": "img-1", "bbox": [0, 0, 10, 10]},
            ),
            _finding(
                "占用疏散通道",
                3,
                ["楼道右侧纸箱"],
                location={"image_id": "img-1", "bbox": [20, 20, 30, 30]},
            ),
        ],
    )
    second = _model("glm-v", [])
    disagreement = detect_disagreement([first, second], ensemble_mode="full")
    result = judge_ensemble([first, second], disagreement)
    assert len(result.final_findings) == 2
    locations = []
    for finding in result.final_findings:
        locations.extend(finding.locations)
    bboxes = [tuple(item["bbox"]) for item in locations]
    assert len(set(bboxes)) == 2


def test_judge_uses_evidence_gap_in_decision():
    first = _model("qwen-vl", [_finding("占用疏散通道", 3)])
    second = _model("glm-v", [_finding("占用疏散通道", 3)])
    disagreement = detect_disagreement([first, second], ensemble_mode="full")
    result = judge_ensemble([first, second], disagreement, evidence=[])
    finding = result.final_findings[0]
    assert finding.evidence_status == "insufficient"
    assert result.need_human_review is True
    assert any("法规证据不足" in reason for reason in result.review_reasons)
