"""LangGraph StateGraph implementation of the assessment workflow."""

from __future__ import annotations

import re
from typing import Any, TypedDict

from app.core.config import get_settings
from app.services.guardrail import EvidenceGuardResult, validate_model_analysis
from app.services.evidence import judge_evidence
from app.services.human_review import decide_human_review
from app.services.ensemble import (
    ModelRunResult,
    MultiModelResult,
    detect_disagreement,
    judge_ensemble,
    run_parallel_analysis,
    standardize_model_runs,
)
from app.services.ensemble.categories import rag_tags_for_category
from app.services.evidence_refine import refine_with_evidence
from app.services.providers import MockProvider, get_provider, get_providers
from app.services.rag import build_evidence_context, get_rag, retrieval_as_evidence
from app.services.report import build_report
from app.services.risk_engine import apply_risk_to_judge, score_findings

try:
    from langgraph.graph import END, START, StateGraph

    HAS_LANGGRAPH = True
except Exception:  # LangGraph 未安装时由 workflow.py 退回函数式流程
    HAS_LANGGRAPH = False


class WorkflowState(TypedDict, total=False):
    description: str
    ocr_texts: list[str]
    images: list
    followup_answer: str | None
    followup_used: int
    settings: Any
    provider: Any
    providers: list
    rag: Any
    analysis: dict[str, Any]
    model_results: list[dict[str, Any]]
    multi_model: dict[str, Any]
    standardized_results: list[dict[str, Any]]
    disagreement: dict[str, Any]
    ensemble_judge: dict[str, Any]
    risk_result: dict[str, Any]
    model_guard: dict[str, Any]
    evidence_guard: dict[str, Any]
    evidence_judge: dict[str, Any]
    evidence_context: str
    analyze_evidence_context: list[str]
    review_reasons: list[str]
    human_review: dict[str, Any]
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
    refined_with_evidence: bool
    evidence_refine_used: bool
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
    rag_context: list[str] = []
    try:
        providers = state.get("providers") or [state["provider"]]
        rag = state["rag"]
        pre_evidence = rag.search(state["description"], top_k=3) if rag.texts else []
        rag_context = [item["text"] for item in pre_evidence]
        multi = run_parallel_analysis(
            providers,
            state["images"],
            state["description"],
            rag_evidence=rag_context,
            ocr_texts=state.get("ocr_texts") or [],
        )
        primary = multi.primary
        result = primary.analysis or {}
        fallback = False
        reason = ""
        if multi.ensemble_mode == "fallback":
            fallback = True
            reason = "; ".join(
                item.error_message for item in multi.results if item.status == "failed"
            )[:200]
    except Exception as exc:
        result = MockProvider().analyze(state["images"], state["description"])
        result["vision_confidence"] = min(float(result.get("vision_confidence", 0.5)), 0.5)
        fallback = True
        reason = str(exc)[:200]
        fallback_run = ModelRunResult(
            provider="mock",
            family="mock",
            model="mock-vision",
            status="mock_fallback",
            error_message=reason,
            retry_count=0,
            analysis=result,
        )
        multi = MultiModelResult(
            ensemble_mode="fallback",
            results=[fallback_run],
            primary=fallback_run,
            succeeded=0,
            failed=0,
            total_latency_ms=0.0,
        )
    standardized = standardize_model_runs(
        [item.model_dump() for item in multi.results]
    )
    disagreement = detect_disagreement(
        standardized,
        ensemble_mode=multi.ensemble_mode,
    )
    model_guard = validate_model_analysis(
        result,
        provider=result.get("provider", ""),
        model=result.get("model", ""),
    )
    return {
        "analysis": result,
        "model_results": [item.model_dump() for item in multi.results],
        "multi_model": multi.to_state(),
        "standardized_results": [item.model_dump() for item in standardized],
        "disagreement": disagreement.model_dump(),
        "model_guard": model_guard.model_dump(),
        "analyze_evidence_context": rag_context,
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
    rule = state.get("rule", {}) or {}
    hint = state.get("hazard_hints") or []
    category = rule.get("category") or (hint[0] if hint else None)
    tags = rag_tags_for_category(category)
    results = state["rag"].search(query, top_k=5, tags=tags) if tags else []
    if not results:
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


def node_refine(state: WorkflowState) -> dict[str, Any]:
    providers = state.get("providers") or [state["provider"]]
    return refine_with_evidence(
        state,
        providers=providers,
        settings=state["settings"],
    )


def node_judge(state: WorkflowState) -> dict[str, Any]:
    weights = state["settings"].confidence_weights
    if len(weights) != 4:
        weights = [0.3, 0.3, 0.2, 0.2]

    vision_conf = state["vision_confidence"]
    retrieval_conf = state.get("retrieval_conf", 0.5)
    rule_score = max(0.15, state.get("rule_score", 0.0))
    rule_conf = rule_score
    if state["provider"].name == "mock":
        rule_conf = min(1.0, max(0.25, rule_score * 0.9 + 0.25))
    llm_conf_raw = state["analysis"].get("llm_confidence", vision_conf)
    llm_conf = vision_conf if llm_conf_raw is None else float(llm_conf_raw)
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
    standardized = state.get("standardized_results") or []
    disagreement = state.get("disagreement") or {}
    evidence = retrieval_as_evidence(state.get("retrieval", []))
    preliminary = judge_ensemble(standardized, disagreement, evidence=evidence)
    category = (
        preliminary.final_findings[0].category
        if preliminary.final_findings
        else state["hazard_hints"][0]
        if state.get("hazard_hints")
        else "待进一步确认"
    )
    scene_text = f"{state['description']}\n{state.get('scene_summary', '')}"
    risk_result = score_findings(
        preliminary.final_findings,
        scene_text=scene_text,
        observations=(state.get("analysis") or {}).get("observations", []),
        severity_hint=preliminary.final_severity,
        evidence_texts=[item.get("text", "") for item in evidence],
    )
    ensemble_judge = judge_ensemble(
        standardized,
        disagreement,
        risk_result=risk_result,
        evidence=evidence,
    )
    apply_risk_to_judge(ensemble_judge, risk_result)
    return {
        "hazard_category": category,
        "risk_level": risk_result.operational_level,
        "confidence": confidence,
        "ensemble_judge": ensemble_judge.model_dump(),
        "risk_result": risk_result.model_dump(),
    }


def node_evidence(state: WorkflowState) -> dict[str, Any]:
    evidence = retrieval_as_evidence(state.get("retrieval", []))
    findings = state.get("ensemble_judge", {}).get("final_findings", [])
    judge_result = judge_evidence(findings, evidence)
    guard = EvidenceGuardResult(
        supported=judge_result.supported,
        support_score=judge_result.support_score,
        evidence_ids=judge_result.evidence_ids,
        unsupported_claims=judge_result.unsupported_claims,
        needs_human_review=judge_result.needs_human_review,
        visual_evidence_count=judge_result.visual_evidence_count,
        retrieval_evidence_count=judge_result.retrieval_evidence_count,
        finding_status=[item.model_dump() for item in judge_result.findings],
    )
    judge = state.get("ensemble_judge")
    if isinstance(judge, dict):
        statuses = {item.finding_id: item for item in judge_result.findings}
        for finding in judge.get("final_findings", []):
            result = statuses.get(finding.get("finding_id"))
            if result:
                finding["evidence_status"] = (
                    "supported"
                    if result.supported and result.visual_evidence_ok
                    else "insufficient"
                )
                finding["support_score"] = result.support_score
                finding["evidence_ids"] = result.evidence_ids
                finding["unsupported_claims"] = result.unsupported_claims
    return {
        "evidence": evidence,
        "evidence_guard": guard.model_dump(),
        "evidence_judge": judge_result.model_dump(),
        "evidence_context": build_evidence_context(evidence),
    }


def node_generate(state: WorkflowState) -> dict[str, Any]:
    report = build_report(state)
    confidence = state.get("confidence", 0.0)
    review = decide_human_review(state)
    status = (
        "awaiting_human_review" if review.need_human_review else "completed"
    )
    return {
        "report": report,
        "conclusion": report["summary"],
        "status": status,
        "review_reasons": review.review_reasons,
        "human_review": review.model_dump(),
    }


def route_after_evidence(state: WorkflowState) -> str:
    review = decide_human_review(state)
    return "human_review" if review.need_human_review else "generate"


def node_human_review(state: WorkflowState) -> dict[str, Any]:
    report = build_report(state)
    review = decide_human_review(state)
    return {
        "report": report,
        "conclusion": report["summary"],
        "status": "awaiting_human_review",
        "review_reasons": review.review_reasons,
        "human_review": review.model_dump(),
    }


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        graph = StateGraph(WorkflowState)
        graph.add_node("analyze", node_analyze)
        graph.add_node("info", node_info)
        graph.add_node("retrieve", node_retrieve)
        graph.add_node("refine", node_refine)
        graph.add_node("judge", node_judge)
        graph.add_node("evidence", node_evidence)
        graph.add_node("generate", node_generate)
        graph.add_node("human_review", node_human_review)
        graph.add_edge(START, "analyze")
        graph.add_edge("analyze", "info")
        graph.add_conditional_edges(
            "info",
            route_after_info,
            {"finish": END, "retrieve": "retrieve"},
        )
        graph.add_edge("retrieve", "refine")
        graph.add_edge("refine", "judge")
        graph.add_edge("judge", "evidence")
        graph.add_conditional_edges(
            "evidence",
            route_after_evidence,
            {"human_review": "human_review", "generate": "generate"},
        )
        graph.add_edge("generate", END)
        graph.add_edge("human_review", END)
        _graph = graph.compile()
    return _graph


def run_langgraph(
    description: str,
    images: list,
    followup_answer: str | None = None,
    followup_used: int = 0,
    *,
    ocr_texts: list[str] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    initial_state: WorkflowState = {
        "description": description,
        "ocr_texts": ocr_texts or [],
        "images": images,
        "followup_answer": followup_answer,
        "followup_used": followup_used,
        "settings": settings,
        "provider": get_provider(),
        "providers": get_providers(),
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
