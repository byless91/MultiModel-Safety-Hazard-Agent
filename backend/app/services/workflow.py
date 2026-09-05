import re
from typing import Any

from app.core.config import get_settings
from app.services.langgraph_flow import HAS_LANGGRAPH, run_langgraph
from app.services.providers import get_provider
from app.services.rag import get_rag
from app.services.report import build_report


def run_workflow(
    description: str,
    images: list,
    followup_answer: str | None = None,
    followup_used: int = 0,
) -> dict[str, Any]:
    if HAS_LANGGRAPH:
        return run_langgraph(description, images, followup_answer, followup_used)
    return run_functional(description, images, followup_answer, followup_used)


def run_functional(
    description: str,
    images: list,
    followup_answer: str | None = None,
    followup_used: int = 0,
) -> dict[str, Any]:
    settings = get_settings()
    state: dict[str, Any] = {
        "description": description,
        "images": images,
        "followup_answer": followup_answer,
        "followup_used": followup_used,
        "settings": settings,
        "provider": get_provider(),
        "rag": get_rag(),
    }
    if followup_answer:
        state["description"] = f"{description}\n补充信息：{followup_answer}"
    state.update(_step_analyze(state))
    state.update(_step_info(state))
    if state.get("needs_more_info"):
        state["status"] = "needs_more_info"
        return state
    state.update(_step_retrieve(state))
    state.update(_step_judge(state))
    state.update(_step_evidence(state))
    state.update(_step_generate(state))
    state["confidence"] = round(state["confidence"], 3)
    state["status"] = "completed" if state["confidence"] >= 0.8 else "needs_review"
    return state


def _step_analyze(state: dict[str, Any]) -> dict[str, Any]:
    result = state["provider"].analyze(state["images"], state["description"])
    return {
        "analysis": result,
        "scene_summary": result.get("scene_summary", ""),
        "hazard_hints": result.get("hazard_hints", []),
        "observations": result.get("observations", []),
        "vision_confidence": float(result.get("vision_confidence", 0.6)),
        "rule": result.get("rule", {}),
        "rule_score": float(result.get("rule_score", 0.0)),
        "keywords": result.get("keywords", []),
    }


def _step_info(state: dict[str, Any]) -> dict[str, Any]:
    low_confidence = state["vision_confidence"] < 0.55
    if low_confidence and state["followup_used"] < state["settings"].max_followups and not state.get(
        "followup_answer"
    ):
        questions = state["rule"].get("followups") or ["请补充隐患位置、危险程度和现场环境。"]
        return {"needs_more_info": True, "followup_questions": questions}
    return {"needs_more_info": False, "followup_questions": []}


def _step_retrieve(state: dict[str, Any]) -> dict[str, Any]:
    query = f"{state['description']}\n{state['scene_summary']}"
    results = state["rag"].search(query, top_k=5)
    vector_confidence = sum(item["score"] for item in results) / max(1, len(results))
    retrieval_confidence = vector_confidence
    if state["provider"].name == "mock" and results:
        lexical_confidence = _keyword_overlap(query, [item["text"] for item in results])
        retrieval_confidence = min(1.0, 0.6 * lexical_confidence + 0.4 * vector_confidence + 0.15)
    return {
        "retrieval": results,
        "retrieval_conf": round(min(1.0, max(0.0, retrieval_confidence)), 3),
    }


def _keyword_overlap(query: str, texts: list[str]) -> float:
    pattern = re.compile(r"[\u4e00-\u9fff]{2,6}|[a-zA-Z0-9_]+")
    query_terms = set(pattern.findall(query))
    if not query_terms:
        return 0.2
    scores = []
    for text in texts:
        text_terms = set(pattern.findall(text))
        scores.append(len(query_terms & text_terms) / len(query_terms))
    return sum(scores) / len(scores) if scores else 0.2


def _step_judge(state: dict[str, Any]) -> dict[str, Any]:
    rule = state.get("rule", {}) or {}
    category = rule.get("category") or (
        state["hazard_hints"][0] if state.get("hazard_hints") else "待进一步确认"
    )
    level = int(rule.get("level", 3))
    weights = state["settings"].confidence_weights
    if len(weights) != 4:
        weights = [0.3, 0.3, 0.2, 0.2]

    vision_conf = state["vision_confidence"]
    retrieval_conf = state.get("retrieval_conf", 0.5)
    rule_score = max(0.15, state.get("rule_score", 0.0))
    rule_conf = rule_score
    if state["provider"].name == "mock":
        rule_conf = min(1.0, max(0.25, rule_score * 0.9 + 0.25))
    llm_conf = float(state["analysis"].get("llm_confidence", vision_conf))
    confidence = (
        weights[0] * vision_conf
        + weights[1] * retrieval_conf
        + weights[2] * rule_conf
        + weights[3] * llm_conf
    )
    if state["provider"].name == "mock" and rule_score >= 0.35:
        rule_based_confidence = min(0.95, 0.68 + rule_score * 0.3)
        confidence = max(confidence, rule_based_confidence)
    confidence = min(0.99, max(0.05, confidence))
    return {"hazard_category": category, "risk_level": level, "confidence": confidence}


def _step_evidence(state: dict[str, Any]) -> dict[str, Any]:
    evidence = [
        {
            "source": item.get("source", "未标注来源"),
            "text": item.get("text", ""),
            "version": item.get("version", ""),
            "tags": item.get("tags", []),
            "score": item.get("score", 0),
        }
        for item in state.get("retrieval", [])
    ]
    return {"evidence": evidence}


def _step_generate(state: dict[str, Any]) -> dict[str, Any]:
    report = build_report(state)
    return {"report": report, "conclusion": report["summary"]}
