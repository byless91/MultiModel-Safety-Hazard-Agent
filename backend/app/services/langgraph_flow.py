"""LangGraph StateGraph implementation of the assessment workflow.

节点实现共享自 workflow_nodes.py；本文件只保留图的编排（节点注册、
条件路由、初始状态装配）。函数式回退路径见 workflow.run_functional。
"""

from __future__ import annotations

from typing import Any, TypedDict

from app.services.human_review import decide_human_review
from app.services.report import build_report
from app.services.workflow_nodes import (
    analyze_with_fallback,
    build_runtime,
    initial_state,
    step_evidence,
    step_info,
    step_judge,
    step_refine,
    step_retrieve,
)

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


# 节点实现直接复用 workflow_nodes；LangGraph 专属的 analyze 兜底语义
# （模型故障降级 Mock、编程错误显式抛出）封装在 analyze_with_fallback 中
node_analyze = analyze_with_fallback
node_info = step_info
node_retrieve = step_retrieve
node_refine = step_refine
node_judge = step_judge
node_evidence = step_evidence


def route_after_info(state: WorkflowState) -> str:
    return "finish" if state.get("needs_more_info") else "retrieve"


def node_generate(state: WorkflowState) -> dict[str, Any]:
    # 与函数式路径的已知差异：此处不做置信度四舍五入（B5 收敛）
    report = build_report(state)
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
    settings: Any | None = None,
    rag: Any | None = None,
    providers: list | None = None,
) -> dict[str, Any]:
    settings, providers, rag = build_runtime(
        settings=settings, rag=rag, providers=providers
    )
    initial: WorkflowState = initial_state(  # type: ignore[assignment]
        description,
        images,
        followup_answer,
        followup_used,
        ocr_texts,
        settings,
        rag,
        providers,
    )
    final_state = get_graph().invoke(initial)
    if not final_state.get("status"):
        final_state["status"] = (
            "needs_more_info" if final_state.get("needs_more_info") else "completed"
        )
    return dict(final_state)
