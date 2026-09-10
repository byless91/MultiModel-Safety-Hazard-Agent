from fastapi.testclient import TestClient

from app.main import app
from app.services.human_review import decide_human_review
from app.services.workflow import run_workflow


def test_no_triggers_completes():
    decision = decide_human_review({"confidence": 0.9})
    assert decision.need_human_review is False
    assert decision.review_reasons == []


def test_disagreement_trigger():
    decision = decide_human_review(
        {
            "confidence": 0.9,
            "disagreement": {
                "need_human_review": True,
                "reasons": ["模型隐患类别不一致"],
            },
        }
    )
    assert decision.need_human_review is True
    assert "模型隐患类别不一致" in decision.review_reasons


def test_high_risk_trigger():
    decision = decide_human_review(
        {"confidence": 0.9, "risk_result": {"review_suggestion": True}}
    )
    assert decision.need_human_review is True
    assert decision.triggers.get("risk_engine") is True


def test_evidence_insufficient_trigger():
    decision = decide_human_review(
        {
            "confidence": 0.9,
            "evidence_judge": {
                "needs_human_review": True,
                "unsupported_claims": ["观察事实缺少法规依据"],
            },
        }
    )
    assert decision.need_human_review is True
    assert any("法规证据不足" in item for item in decision.review_reasons)


def test_fallback_trigger():
    decision = decide_human_review(
        {
            "confidence": 0.9,
            "model_results": [{"status": "mock_fallback"}],
        }
    )
    assert decision.triggers.get("fallback") is True
    assert decision.need_human_review is True


def test_low_confidence_trigger():
    decision = decide_human_review({"confidence": 0.6})
    assert decision.triggers.get("low_confidence") is True
    assert decision.need_human_review is True


def test_risk_reason_wording_matches_actual_level():
    decision = decide_human_review(
        {
            "confidence": 0.9,
            "risk_result": {"review_suggestion": True, "risk_level": "low"},
        }
    )
    assert decision.need_human_review is True
    assert decision.triggers.get("risk_engine") is True
    assert not any("风险规则引擎判定为高风险" in item for item in decision.review_reasons)
    assert any("不确定性" in item for item in decision.review_reasons)


def test_risk_model_conflict_trigger():
    decision = decide_human_review(
        {
            "confidence": 0.9,
            "ensemble_judge": {"final_severity": 3},
            "risk_result": {"risk_level": "low"},
        }
    )
    assert decision.triggers.get("risk_model_conflict") is True
    assert decision.need_human_review is True


def test_image_quality_trigger():
    decision = decide_human_review({"confidence": 0.9, "vision_confidence": 0.4})
    assert decision.triggers.get("image_quality") is True
    assert decision.need_human_review is True


def test_negated_safe_claim_forces_review():
    decision = decide_human_review(
        {
            "confidence": 0.9,
            "description": "现场安全，没有安全隐患",
            "ensemble_judge": {"final_findings": []},
        }
    )
    assert decision.triggers.get("negated_claim") is True
    assert any("禁止自动通过" in item for item in decision.review_reasons)


def test_ocr_safe_claim_forces_review():
    decision = decide_human_review(
        {
            "confidence": 0.9,
            "description": "楼道看起来正常",
            "ocr_texts": ["现场安全"],
            "ensemble_judge": {"final_findings": []},
        }
    )
    assert decision.triggers.get("negated_claim") is True


def test_high_risk_workflow_uses_awaiting_status():
    state = run_workflow(description="小区楼道堆放纸箱杂物，堵塞疏散通道", images=[])
    assert state["status"] == "awaiting_human_review"
    assert state["review_reasons"]
    assert state["human_review"]["need_human_review"] is True
    assert state["human_review"]["triggers"]["risk_engine"] is True


def test_api_persists_review_reasons_and_confirm_flow():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/assessments",
            data={"description": "现场有异常"},
        )
        assert created.status_code == 201
        first = created.json()
        assert first["status"] == "needs_more_info"

        followup = client.post(
            f"/api/v1/assessments/{first['id']}/followup",
            json={"answer": "情况不明，需要人工查看"},
        )
        assert followup.status_code == 200
        body = followup.json()
        assert body["status"] == "awaiting_human_review"
        assert body["awaiting_human_review"] is True
        assert body["review_reasons"]
        assert body["human_review"]["need_human_review"] is True

        confirmed = client.post(
            f"/api/v1/assessments/{first['id']}/confirm",
            json={"confirmed": True},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "confirmed"
