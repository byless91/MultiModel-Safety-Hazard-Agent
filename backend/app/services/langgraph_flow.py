"""LangGraph StateGraph implementation of the assessment workflow."""

from __future__ import annotations

import re
from typing import Any, TypedDict

from app.core.config import get_settings
from app.services.providers import MockProvider, get_provider
from app.services.rag import get_rag
from app.services.report import build_report

try:
    from langgraph.graph import END, START, StateGraph

    HAS_LANGGRAPH = True
except Exception:  # LangGraph 未安装时由 workflow.py 退回函数式流程
    HAS_LANGGRAPH = False


class WorkflowState(TypedDict, total=False):
    description: str
    images: list
    followup_answer: str | None
    followup_used: int
    settings: Any
    provider: Any
    rag: Any
    analysis: dict[str, Any]
    scene_summary: str
    hazard_hints: list[str]
    observations: list[str]
    vision_confidence: float
    rule: dict[str, Any]
    rule_score: float
    keywords: list[str]
    needs_more_info: bool
    followup_questions: list[str]
    retrieval: list[dict[str, Any]]
    retrieval_conf: float
    hazard_category: str | None
    risk_level: int | None
    confidence: float
    evidence: list[dict[str, Any]]
    report: dict[str, Any]
    conclusion: str
    status: str
    analysis_fallback: bool
    fallback_reason: str


def node_analyze(state: WorkflowState) -> dict[str, Any]:
    try:
        result = state["provider"].analyze(state["images"], state["description"])
        fallback = False
        reason = ""
    except Exception as exc:
        result = MockProvider().analyze(state["images"], state["description"])
        result["vision_confidence"] = min(float(result.get("vision_confidence", 0.5)), 0.5)
        fallback = True
        reason = str(exc)[:200]
    return {
        "analysis": result,
        "scene_summary": result.get("scene_summary", ""),
        "hazard_hints": result.get("hazard_hints", []),
        "observations": result.get("observations", []),
        "vision_confidence": float(result.get("vision_confidence", 0.6)),
        "rule": result.get("rule", {}),
        "rule_score": float(result.get("rule_score", 0.0)),
        "keywords": result.get("keywords", []),
        "analysis_fallback": fallback,
        "fallback_reason": reason,
    }


def node_info(state: WorkflowState) -> dict[str, Any]:
    low_confidence = state.get("vision_confidence", 0.0) < 0.55
    can_ask = state.get("followup_used", 0) < state["settings"].max_followups
    if low_confidence and can_ask and not state.get("followup_answer"):
        questions = state.get("rule", {}).get("followups") or [
            "请补充隐患位置、危险程度和现场环境。"
        ]
        return {"needs_more_info": True, "followup_questions": questions}
    return {"needs_more_info": False, "followup_questions": []}


def route_after_info(state: WorkflowState) -> str:
    return "finish" if state.get("needs_more_info") else "retrieve"


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


def node_retrieve(state: WorkflowState) -> dict[str, Any]:
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


def node_judge(state: WorkflowState) -> dict[str, Any]:
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


def node_evidence(state: WorkflowState) -> dict[str, Any]:
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


def node_generate(state: WorkflowState) -> dict[str, Any]:
    report = build_report(state)
    confidence = state.get("confidence", 0.0)
    status = "completed" if confidence >= 0.8 else "needs_review"
    return {"report": report, "conclusion": report["summary"], "status": status}


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        graph = StateGraph(WorkflowState)
        graph.add_node("analyze", node_analyze)
        graph.add_node("info", node_info)
        graph.add_node("retrieve", node_retrieve)
        graph.add_node("judge", node_judge)
        graph.add_node("evidence", node_evidence)
        graph.add_node("generate", node_generate)
        graph.add_edge(START, "analyze")
        graph.add_edge("analyze", "info")
        graph.add_conditional_edges(
            "info",
            route_after_info,
            {"finish": END, "retrieve": "retrieve"},
        )
        graph.add_edge("retrieve", "judge")
        graph.add_edge("judge", "evidence")
        graph.add_edge("evidence", "generate")
        graph.add_edge("generate", END)
        _graph = graph.compile()
    return _graph


def run_langgraph(
    description: str,
    images: list,
    followup_answer: str | None = None,
    followup_used: int = 0,
) -> dict[str, Any]:
    settings = get_settings()
    initial_state: WorkflowState = {
        "description": description,
        "images": images,
        "followup_answer": followup_answer,
        "followup_used": followup_used,
        "settings": settings,
        "provider": get_provider(),
        "rag": get_rag(),
    }
    if followup_answer:
        initial_state["description"] = f"{description}\n补充信息：{followup_answer}"
    final_state = get_graph().invoke(initial_state)
    if not final_state.get("status"):
        final_state["status"] = (
            "needs_more_info" if final_state.get("needs_more_info") else "completed"
        )
    return dict(final_state)

