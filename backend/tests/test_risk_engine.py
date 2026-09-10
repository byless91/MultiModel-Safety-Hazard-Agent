from app.services.risk_engine import apply_risk_to_judge, score_findings
from app.services.risk_engine.rules import RULE_VERSION


def _finding(category: str, severity: int | None, facts: list[str]) -> dict:
    return {
        "category": category,
        "final_severity": severity,
        "observed_facts": facts,
    }


def test_fire_exit_blocked_scores_high():
    risk = score_findings(
        [_finding("占用疏散通道", 3, ["疏散通道被纸箱堵塞", "通行受阻"])],
        scene_text="小区楼道堆放杂物",
    )
    assert risk.risk_score >= 70
    assert risk.risk_level == "high"
    assert risk.operational_level == 1
    assert risk.rule_version == RULE_VERSION
    assert risk.factor_scores
    assert risk.evidence_used
    assert "category_base:占用疏散通道" in risk.triggered_rules
    assert any(rule.startswith("exposure_keyword:") for rule in risk.triggered_rules)
    assert risk.review_suggestion is True


def test_minor_public_area_stays_low():
    risk = score_findings(
        [_finding("公共区域安全隐患", 1, ["护栏轻微锈蚀"])],
        scene_text="社区公园",
    )
    assert risk.risk_score < 70
    assert risk.risk_level in ("low", "medium")
    assert risk.operational_level in (2, 3)


def test_immediate_danger_keywords_boost_score():
    evidence = ["危险化学品储存场所应采取防泄漏措施"]
    base = score_findings(
        [_finding("危险化学品存储不规范", 2, ["仓库堆放油桶"])],
        scene_text="厂区仓库",
        evidence_texts=evidence,
    )
    boosted = score_findings(
        [_finding("危险化学品存储不规范", 2, ["仓库堆放油桶", "燃气泄漏", "有异味"])],
        scene_text="厂区仓库",
        evidence_texts=evidence,
    )
    assert boosted.risk_score > base.risk_score
    assert "danger_keyword:泄漏" in boosted.triggered_rules
    no_evidence = score_findings(
        [_finding("危险化学品存储不规范", 2, ["仓库堆放油桶", "燃气泄漏", "有异味"])],
        scene_text="厂区仓库",
    )
    assert no_evidence.risk_score == base.risk_score


def test_unknown_category_and_missing_severity_force_review():
    unknown = score_findings(
        [_finding("未知新型风险", 1, ["现场人员倒地"])],
        scene_text="小区楼道",
    )
    assert unknown.review_suggestion is True
    assert any(rule.startswith("unknown_category:") for rule in unknown.triggered_rules)

    missing = score_findings(
        [_finding("公共区域安全隐患", None, ["井盖破损"])],
        scene_text="小区道路",
    )
    assert missing.review_suggestion is True
    assert "severity_missing" in missing.triggered_rules


def test_model_severity_hint_has_limited_weight():
    low = score_findings(
        [_finding("电气线路隐患", 1, ["电线裸露"])],
        scene_text="车间",
    )
    high = score_findings(
        [_finding("电气线路隐患", 3, ["电线裸露"])],
        scene_text="车间",
    )
    assert high.risk_score > low.risk_score
    assert high.risk_score - low.risk_score <= 15


def test_no_findings_scores_low_but_suggests_review():
    risk = score_findings([], scene_text="空场")
    assert risk.risk_score == 20
    assert risk.risk_level == "low"
    assert risk.triggered_rules == []
    assert risk.review_suggestion is True


def test_apply_risk_updates_judge_and_findings():
    from app.services.ensemble.judge import EnsembleJudgeResult, FinalFinding

    judge = EnsembleJudgeResult(
        mode="pair",
        final_findings=[
            FinalFinding(finding_id="x", category="占用疏散通道", final_severity=3)
        ],
        final_severity=3,
        confidence=0.9,
    )
    risk = score_findings(judge.final_findings, scene_text="楼道")
    apply_risk_to_judge(judge, risk)
    assert judge.risk_score == risk.risk_score
    assert judge.risk_level == "high"
    assert judge.rule_version == RULE_VERSION
    assert judge.final_findings[0].risk_score == risk.risk_score


def test_workflow_state_contains_risk_result():
    from app.services.workflow import run_workflow

    state = run_workflow(description="小区楼道堆放纸箱杂物，堵塞疏散通道", images=[])
    risk = state["risk_result"]
    assert risk["risk_level"] == "high"
    assert risk["risk_score"] >= 70
    assert state["risk_result"]["triggered_rules"]
    assert state["ensemble_judge"]["risk_level"] == "high"
    assert state["ensemble_judge"]["rule_version"] == RULE_VERSION
