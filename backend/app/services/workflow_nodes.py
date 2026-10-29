"""两条执行路径（LangGraph 图 / 函数式回退）共享的节点实现。

LangGraph 未安装时 ``workflow.run_functional`` 退回函数式流程；两条路径
必须产出一致结果。节点逻辑只在此处实现一份，任何改动只需改这里。

已知且刻意保留的路径差异（B5 收敛）：
- 函数式路径在复核判定前会把 confidence 四舍五入到 3 位小数，LangGraph
  路径的 node_generate 不做四舍五入；
- 函数式路径的 analyze 无 Mock 兜底（异常直接上抛），LangGraph 路径经
  ``analyze_with_fallback`` 对模型故障降级 Mock、对编程错误显式抛出。
"""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from typing import Any

from app.core.config import get_settings
from app.services.ensemble import (
    ModelRunResult,
    MultiModelResult,
    detect_disagreement,
    judge_ensemble,
    run_parallel_analysis,
    standardize_model_runs,
)
from app.services.ensemble.categories import rag_tags_for_category
from app.services.evidence import judge_evidence
from app.services.evidence_refine import refine_with_evidence
from app.services.finding_identity import ensure_unique_finding_ids
from app.services.guardrail import EvidenceGuardResult, validate_model_analysis
from app.services.providers import MockProvider, build_providers, get_providers
from app.services.rag import (
    RAGService,
    build_evidence_context,
    get_rag,
    retrieval_as_evidence,
)
from app.services.report import build_report
from app.services.risk_engine import apply_risk_to_judge, score_findings

logger = logging.getLogger("safety_hazard.workflow")


def build_runtime(
    *,
    settings: Any | None = None,
    rag: Any | None = None,
    providers: list | None = None,
) -> tuple[Any, list, Any]:
    """两条路径共用的运行时装配：settings/providers/rag 的默认值解析。"""
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
    return settings, providers, rag


def initial_state(
    description: str,
    images: list,
    followup_answer: str | None,
    followup_used: int,
    ocr_texts: list[str] | None,
    settings: Any,
    rag: Any,
    providers: list,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "description": description,
        "ocr_texts": ocr_texts or [],
        "images": images,
        "followup_answer": followup_answer,
        "followup_used": followup_used,
        "settings": settings,
        "provider": providers[0],
        "providers": providers,
        "rag": rag,
    }
    if followup_answer:
        state["description"] = f"{description}\n补充信息：{followup_answer}"
    return state


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


def _analysis_state(
    state: dict[str, Any],
    multi: MultiModelResult,
    rag_context: list[str],
) -> dict[str, Any]:
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


def step_analyze(state: dict[str, Any]) -> dict[str, Any]:
    from app.services import llm_ledger

    providers = state.get("providers") or [state["provider"]]
    rag = state["rag"]
    pre_evidence = rag.search(state["description"], top_k=3) if rag.texts else []
    if not state["settings"].enable_evidence_rag:
        pre_evidence = []
    rag_context = [item["text"] for item in pre_evidence]
    purpose_token = llm_ledger.current_purpose.set("analyze")
    try:
        multi = run_parallel_analysis(
            providers,
            state["images"],
            state["description"],
            rag_evidence=rag_context,
            ocr_texts=state.get("ocr_texts") or [],
        )
    finally:
        llm_ledger.current_purpose.reset(purpose_token)
    return _analysis_state(state, multi, rag_context)


def analyze_with_fallback(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph 路径的 analyze 节点：模型故障降级 Mock，编程错误显式抛出。"""
    try:
        return step_analyze(state)
    except (KeyError, TypeError, AttributeError, IndexError, NameError):
        # 编程错误不允许被 Mock 兜底掩盖：显式抛出，让请求失败并留下完整堆栈
        logger.exception("analyze 节点出现编程错误，拒绝降级为 Mock")
        raise
    except Exception as exc:  # 模型/网络类故障：降级 Mock，但必须留下日志与原因
        logger.warning(
            "多模型分析失败，已降级 Mock 兜底：%s",
            str(exc)[:200],
            exc_info=True,
        )
        result = MockProvider().analyze(state["images"], state["description"])
        result["vision_confidence"] = min(float(result.get("vision_confidence", 0.5)), 0.5)
        fallback_run = ModelRunResult(
            provider="mock",
            family="mock",
            model="mock-vision",
            status="mock_fallback",
            error_message=str(exc)[:200],
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
        return _analysis_state(state, multi, rag_context=[])


def step_info(state: dict[str, Any]) -> dict[str, Any]:
    low_confidence = state.get("vision_confidence", 0.0) < 0.55
    can_ask = state.get("followup_used", 0) < state["settings"].max_followups
    if low_confidence and can_ask and not state.get("followup_answer"):
        questions = state.get("rule", {}).get("followups") or [
            "请补充隐患位置、危险程度和现场环境。"
        ]
        return {"needs_more_info": True, "followup_questions": questions}
    return {"needs_more_info": False, "followup_questions": []}


def step_retrieve(state: dict[str, Any]) -> dict[str, Any]:
    if not state["settings"].enable_evidence_rag:
        return {"retrieval": [], "retrieval_conf": 0.0}
    query = f"{state['description']}\n{state['scene_summary']}"
    rule = state.get("rule", {}) or {}
    hint = state.get("hazard_hints") or []
    category = rule.get("category") or (hint[0] if hint else None)
    tags = rag_tags_for_category(category)
    top_k = int(getattr(state["settings"], "retrieval_top_k", 5))
    results = state["rag"].search(query, top_k=top_k, tags=tags) if tags else []
    if not results:
        results = state["rag"].search(query, top_k=top_k)
    vector_confidence = sum(item["score"] for item in results) / max(1, len(results))
    retrieval_confidence = vector_confidence
    # MOCK_DEMO_BOOST：演示模式显式开关（默认关）。生产与评测路径不再有
    # 隐藏的 mock 特判——此前该分支会系统性抬升 mock 置信度污染评测（C7）
    if (
        getattr(state["settings"], "mock_demo_boost", False)
        and state["provider"].name == "mock"
        and results
    ):
        lexical_confidence = _keyword_overlap(query, [item["text"] for item in results])
        retrieval_confidence = min(1.0, 0.6 * lexical_confidence + 0.4 * vector_confidence + 0.15)
    return {
        "retrieval": results,
        "retrieval_conf": round(min(1.0, max(0.0, retrieval_confidence)), 3),
    }


def step_refine(state: dict[str, Any]) -> dict[str, Any]:
    providers = state.get("providers") or [state["provider"]]
    return refine_with_evidence(
        state,
        providers=providers,
        settings=state["settings"],
    )


def step_judge(state: dict[str, Any]) -> dict[str, Any]:
    weights = state["settings"].confidence_weights
    if len(weights) != 4:
        weights = [0.3, 0.3, 0.2, 0.2]

    vision_conf = state["vision_confidence"]
    retrieval_conf = state.get("retrieval_conf", 0.5)
    rule_score = max(0.15, state.get("rule_score", 0.0))
    rule_conf = rule_score
    demo_boost = (
        getattr(state["settings"], "mock_demo_boost", False)
        and state["provider"].name == "mock"
    )
    if demo_boost:
        rule_conf = min(1.0, max(0.25, rule_score * 0.9 + 0.25))
    llm_conf_raw = state["analysis"].get("llm_confidence", vision_conf)
    llm_conf = vision_conf if llm_conf_raw is None else float(llm_conf_raw)
    confidence = (
        weights[0] * vision_conf
        + weights[1] * retrieval_conf
        + weights[2] * rule_conf
        + weights[3] * llm_conf
    )
    if demo_boost and rule_score >= 0.35:
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


def step_evidence(state: dict[str, Any]) -> dict[str, Any]:
    evidence = retrieval_as_evidence(state.get("retrieval", []))
    judge = deepcopy(state.get("ensemble_judge") or {})
    findings = ensure_unique_finding_ids(judge.get("final_findings", []))
    judge["final_findings"] = findings
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
        "ensemble_judge": judge,
    }


def step_generate(state: dict[str, Any]) -> dict[str, Any]:
    report = build_report(state)
    return {"report": report, "conclusion": report["summary"]}
