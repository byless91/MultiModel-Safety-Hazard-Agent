import re
from typing import Any

from app.core.config import get_settings
from app.services.ensemble import (
    detect_disagreement,
    judge_ensemble,
    run_parallel_analysis,
    standardize_model_runs,
)
from app.services.ensemble.categories import rag_tags_for_category
from app.services.evidence_refine import refine_with_evidence
from app.services.langgraph_flow import HAS_LANGGRAPH, run_langgraph
from app.services.guardrail import EvidenceGuardResult, validate_model_analysis
from app.services.evidence import judge_evidence
from app.services.human_review import decide_human_review
from app.services.providers import (
    build_providers,
    get_provider,
    get_providers,
)
from app.services.rag import (
    RAGService,
    build_evidence_context,
    get_rag,
    retrieval_as_evidence,
)
from app.services.report import build_report
from app.services.risk_engine import apply_risk_to_judge, score_findings


def run_workflow(
    description: str,
    images: list,
    followup_answer: str | None = None,
    followup_used: int = 0,
    *,
    ocr_texts: list[str] | None = None,
    settings: Any | None = None,
    rag: Any | None = None,
    providers: list | None = None,
) -> dict[str, Any]:
    if HAS_LANGGRAPH:
        return run_langgraph(
            description,
            images,
            followup_answer,
            followup_used,
            ocr_texts=ocr_texts,
            settings=settings,
            rag=rag,
            providers=providers,
        )
    return run_functional(
        description,
        images,
        followup_answer,
        followup_used,
        ocr_texts=ocr_texts,
        settings=settings,
        rag=rag,
        providers=providers,
    )


def run_functional(
    description: str,
    images: list,
    followup_answer: str | None = None,
    followup_used: int = 0,
    *,
    ocr_texts: list[str] | None = None,
    settings: Any | None = None,
    rag: Any | None = None,
    providers: list | None = None,
) -> dict[str, Any]:
    if settings is None:
        settings = get_settings()
        if providers is None:
            providers = get_providers()
        provider = providers[0]
        if rag is None:
            rag = get_rag()
    else:
        if providers is None:
            providers = build_providers(settings)
        provider = providers[0]
        if rag is None:
            rag = RAGService(settings, provider)
    state: dict[str, Any] = {
        "description": description,
        "ocr_texts": ocr_texts or [],
        "images": images,
        "followup_answer": followup_answer,
        "followup_used": followup_used,
        "settings": settings,
        "provider": provider,
        "providers": providers,
        "rag": rag,
    }
    if followup_answer:
        state["description"] = f"{description}\n补充信息：{followup_answer}"
    state.update(_step_analyze(state))
    state.update(_step_info(state))
    if state.get("needs_more_info"):
        state["status"] = "needs_more_info"
        return state
    state.update(_step_retrieve(state))
    state.update(_step_refine(state))
    state.update(_step_judge(state))
    state.update(_step_evidence(state))
    state.update(_step_generate(state))
    state["confidence"] = round(state["confidence"], 3)
    review = decide_human_review(state)
    state["review_reasons"] = review.review_reasons
    state["human_review"] = review.model_dump()
    state["status"] = (
        "awaiting_human_review" if review.need_human_review else "completed"
    )
    return state


def _step_analyze(state: dict[str, Any]) -> dict[str, Any]:
    providers = state.get("providers") or [state["provider"]]
    rag = state["rag"]
    pre_evidence = rag.search(state["description"], top_k=3) if rag.texts else []
    if not state["settings"].enable_evidence_rag:
        pre_evidence = []
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
    fallback = multi.ensemble_mode == "fallback"
    reason = ""
    if fallback:
        reason = "; ".join(
            item.error_message for item in multi.results if item.status == "failed"
        )[:200]
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


def _step_info(state: dict[str, Any]) -> dict[str, Any]:
    low_confidence = state["vision_confidence"] < 0.55
    if low_confidence and state["followup_used"] < state["settings"].max_followups and not state.get(
        "followup_answer"
    ):
        questions = state["rule"].get("followups") or ["请补充隐患位置、危险程度和现场环境。"]
        return {"needs_more_info": True, "followup_questions": questions}
    return {"needs_more_info": False, "followup_questions": []}


def _step_retrieve(state: dict[str, Any]) -> dict[str, Any]:
    if not state["settings"].enable_evidence_rag:
        return {"retrieval": [], "retrieval_conf": 0.0}
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


def _step_refine(state: dict[str, Any]) -> dict[str, Any]:
    providers = state.get("providers") or [state["provider"]]
    return refine_with_evidence(
        state,
        providers=providers,
        settings=state["settings"],
    )


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
    if state["settings"].enable_risk_engine:
        risk_result = score_findings(
            preliminary.final_findings,
            scene_text=scene_text,
            observations=(state.get("analysis") or {}).get("observations", []),
            severity_hint=preliminary.final_severity,
            evidence_texts=[item.get("text", "") for item in evidence],
        )
    else:
        risk_result = None
    ensemble_judge = judge_ensemble(
        standardized,
        disagreement,
        risk_result=risk_result,
        evidence=evidence,
    )
    if risk_result is not None:
        apply_risk_to_judge(ensemble_judge, risk_result)
    return {
        "hazard_category": category,
        "risk_level": risk_result.operational_level if risk_result else None,
        "confidence": confidence,
        "ensemble_judge": ensemble_judge.model_dump(),
        "risk_result": risk_result.model_dump() if risk_result else None,
    }


def _step_evidence(state: dict[str, Any]) -> dict[str, Any]:
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


def _step_generate(state: dict[str, Any]) -> dict[str, Any]:
    report = build_report(state)
    return {"report": report, "conclusion": report["summary"]}
