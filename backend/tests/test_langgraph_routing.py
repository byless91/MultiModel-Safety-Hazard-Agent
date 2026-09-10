from app.services.langgraph_flow import (
    node_generate,
    node_human_review,
    route_after_evidence,
)
from app.services.workflow import run_workflow


def _clean_state() -> dict:
    return {
        "confidence": 0.9,
        "evidence": [],
        "analysis": {},
        "disagreement": {},
        "ensemble_judge": {},
        "risk_result": {},
        "evidence_judge": {"needs_human_review": False},
        "model_guard": {"valid": True},
        "model_results": [],
        "hazard_category": None,
        "risk_level": 3,
    }


def test_route_after_evidence_routes_clean_state_to_generate():
    assert route_after_evidence(_clean_state()) == "generate"


def test_route_after_evidence_routes_high_risk_to_review():
    state = _clean_state()
    state["risk_result"] = {"review_suggestion": True}
    assert route_after_evidence(state) == "human_review"


def test_route_after_evidence_routes_evidence_gap_to_review():
    state = _clean_state()
    state["evidence_judge"] = {
        "needs_human_review": True,
        "unsupported_claims": ["缺少法规依据"],
    }
    assert route_after_evidence(state) == "human_review"


def test_node_human_review_builds_report_and_status():
    state = _clean_state()
    state["confidence"] = 0.5
    result = node_human_review(state)
    assert result["status"] == "awaiting_human_review"
    assert result["report"]
    assert result["conclusion"]
    assert result["human_review"]["need_human_review"] is True


def test_node_generate_completes_without_triggers():
    result = node_generate(_clean_state())
    assert result["status"] == "completed"
    assert result["report"]


def test_node_generate_negated_claim_routes_to_review():
    state = _clean_state()
    state["description"] = "现场安全，没有安全隐患"
    state["ensemble_judge"] = {
        "final_findings": [],
        "need_human_review": True,
        "review_reasons": ["模型未检出明显隐患，需人工确认后再放行"],
    }
    result = node_generate(state)
    assert result["status"] == "awaiting_human_review"
    assert result["human_review"]["triggers"].get("negated_claim") is True


def test_workflow_takes_conditional_review_path():
    state = run_workflow(description="小区楼道堆放纸箱杂物，堵塞疏散通道", images=[])
    assert state["status"] == "awaiting_human_review"
    assert state["human_review"]["need_human_review"] is True
    assert state["review_reasons"]
    assert state["report"]
    assert state["conclusion"]
    assert state["ensemble_judge"]["risk_score"] is not None
