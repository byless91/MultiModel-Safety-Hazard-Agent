"""Optional second-pass model analysis grounded in the final retrieved evidence."""

from __future__ import annotations

from typing import Any

from app.services.ensemble import (
    detect_disagreement,
    run_parallel_analysis,
    standardize_model_runs,
)
from app.services.guardrail import validate_model_analysis


def refine_with_evidence(
    state: dict[str, Any],
    *,
    providers: list[Any],
    settings: Any,
) -> dict[str, Any]:
    """Re-run vision analysis with final evidence when real providers are configured.

    Mock providers ignore the evidence prompt and are deterministic, so refining
    in mock mode would only double the latency without changing the result.
    """
    if state.get("refined_with_evidence"):
        return {}
    if not getattr(settings, "refine_with_evidence", True):
        return {}
    retrieval = state.get("retrieval") or state.get("evidence") or []
    texts = [
        str(item.get("text") or "")
        for item in retrieval
        if isinstance(item, dict) and item.get("text")
    ]
    if not texts:
        return {}
    if not any(getattr(provider, "name", "") != "mock" for provider in providers):
        return {}

    multi = run_parallel_analysis(
        providers,
        state.get("images") or [],
        state.get("description") or "",
        rag_evidence=texts,
        ocr_texts=state.get("ocr_texts") or [],
    )
    primary = multi.primary
    result = primary.analysis or {}
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
    fallback = multi.ensemble_mode == "fallback"
    reason = (
        "; ".join(
            item.error_message
            for item in multi.results
            if item.status == "failed"
        )[:200]
        if fallback
        else ""
    )
    return {
        "analysis": result,
        "model_results": [item.model_dump() for item in multi.results],
        "multi_model": multi.to_state(),
        "standardized_results": [item.model_dump() for item in standardized],
        "disagreement": disagreement.model_dump(),
        "model_guard": model_guard.model_dump(),
        "scene_summary": result.get("scene_summary", ""),
        "hazard_hints": result.get("hazard_hints", []),
        "observations": result.get("observations", []),
        "vision_confidence": float(result.get("vision_confidence", 0.6)),
        "rule": result.get("rule", {}),
        "rule_score": float(result.get("rule_score", 0.0)),
        "keywords": result.get("keywords", []),
        "analysis_fallback": fallback,
        "fallback_reason": reason,
        "evidence_refine_used": True,
        "refined_with_evidence": True,
    }
