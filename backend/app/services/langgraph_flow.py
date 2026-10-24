"""LangGraph StateGraph implementation of the assessment workflow.

节点实现共享自 workflow_nodes.py；本文件只保留图的编排（节点注册、
条件路由、初始状态装配）。函数式回退路径见 workflow.run_functional。

两种图变体（B3/WP1.2）：
- sync 变体（默认）：无 checkpointer、info 节点走 step_info 语义，
  与 B2 之前行为完全一致；
- async 变体（use_checkpointer=True）：挂 SqliteSaver、info 节点用
  interrupt() 挂起，followup 通过 Command(resume=...) 从断点恢复，
  不再重新调用视觉模型。
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from collections.abc import Callable
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

try:
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command, interrupt

    HAS_CHECKPOINTER = True
except Exception:  # langgraph-checkpoint-sqlite 未安装：async 变体不可用
    HAS_CHECKPOINTER = False

logger = logging.getLogger("safety_hazard.workflow")

ProgressCallback = Callable[[str], None]


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
    confirmed: bool
    analysis_fallback: bool
    fallback_reason: str


# analyze 节点（含模型故障降级、编程错误显式抛出的兜底语义）两条变体共用
node_analyze = analyze_with_fallback
# sync 变体的 info/retrieve/refine/judge/evidence 节点直接复用 workflow_nodes；
# async 变体的 info 节点用 interrupt 挂起（见 node_info_interrupt）
node_info_sync = step_info
node_retrieve = step_retrieve
node_refine = step_refine
node_judge = step_judge
node_evidence = step_evidence


def node_info_interrupt(state: WorkflowState) -> dict[str, Any]:
    """async 变体的 info 节点：信息不足时 interrupt() 挂起等待追问回答。

    首次运行在 interrupt 处抛出 GraphInterrupt，图状态由 checkpointer 持久化；
    恢复时 interrupt() 返回追问回答，补充信息合入 description 后继续流转。
    """
    base = step_info(state)
    if not base["needs_more_info"]:
        return base
    questions = base["followup_questions"]
    answer = interrupt(questions)
    return {
        **base,
        "needs_more_info": False,
        "followup_questions": questions,
        "followup_answer": answer,
        "description": f"{state['description']}\n补充信息：{answer}",
    }


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


def route_after_info(state: WorkflowState) -> str:
    return "finish" if state.get("needs_more_info") else "retrieve"


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


_saver = None
_graphs: dict[bool, Any] = {}


def _strip_runtime_handles(obj: Any) -> Any:
    """把不可序列化的运行时句柄（provider/rag/settings）替换为占位标记。

    checkpoint 只持久化数据；真实句柄在 resume 时经 Command(update=...)
    重新注入，保证 checkpoint 可跨进程/跨版本移植。
    """
    from pydantic_settings import BaseSettings

    from app.services.providers.base import BaseProvider
    from app.services.rag import RAGService

    if isinstance(obj, (bool, int, float, str, type(None))):
        return obj
    if isinstance(obj, (BaseProvider, RAGService)) or isinstance(obj, BaseSettings):
        return {"__runtime_handle__": type(obj).__name__}
    if isinstance(obj, dict):
        return {key: _strip_runtime_handles(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_strip_runtime_handles(value) for value in obj]
    return obj


class _RuntimeHandleSerializer(JsonPlusSerializer):
    """SqliteSaver 的 serde：持久化前剥离运行时句柄。"""

    def dumps_typed(self, obj):
        return super().dumps_typed(_strip_runtime_handles(obj))


def _get_saver():
    """惰性创建共享 SqliteSaver（串行 worker 下单连接无并发写）。"""
    global _saver
    if _saver is None:
        from app.core.config import get_settings

        path = get_settings().langgraph_checkpoint_path
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        _saver = SqliteSaver(conn, serde=_RuntimeHandleSerializer())
    return _saver


def _compile_graph(use_checkpointer: bool = False):
    graph = StateGraph(WorkflowState)
    graph.add_node("analyze", analyze_with_fallback)
    graph.add_node("info", node_info_interrupt if use_checkpointer else node_info_sync)
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
    if use_checkpointer:
        if not HAS_CHECKPOINTER:
            raise RuntimeError("use_checkpointer=True 需要 langgraph-checkpoint-sqlite")
        return graph.compile(checkpointer=_get_saver())
    return graph.compile()


def get_graph(use_checkpointer: bool = False):
    """获取（并缓存）图变体：sync 默认变体 / async 检查点变体。"""
    if use_checkpointer not in _graphs:
        _graphs[use_checkpointer] = _compile_graph(use_checkpointer)
    return _graphs[use_checkpointer]


def _extract_interrupt_payload(interrupts) -> list[str] | None:
    if not interrupts:
        return None
    first = interrupts[0]
    payload = getattr(first, "value", None)
    if isinstance(payload, (list, tuple)) and payload:
        return [str(item) for item in payload]
    return [str(payload)] if payload is not None else ["请补充隐患位置、危险程度和现场环境。"]


def _finalize_status(final_state: dict[str, Any]) -> dict[str, Any]:
    if not final_state.get("status"):
        final_state["status"] = (
            "needs_more_info" if final_state.get("needs_more_info") else "completed"
        )
    return final_state


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
    progress: ProgressCallback | None = None,
    thread_id: str | None = None,
    use_checkpointer: bool = False,
) -> dict[str, Any]:
    settings, providers, rag = build_runtime(
        settings=settings, rag=rag, providers=providers
    )
    initial = initial_state(
        description,
        images,
        followup_answer,
        followup_used,
        ocr_texts,
        settings,
        rag,
        providers,
    )
    config = {"configurable": {"thread_id": thread_id or uuid.uuid4().hex}}
    graph = get_graph(use_checkpointer=use_checkpointer)
    final_state: dict[str, Any] = dict(initial)
    interrupts = None
    if progress is None:
        result = dict(graph.invoke(initial, config))
        interrupts = result.pop("__interrupt__", None)
        final_state = result if result else final_state
    else:
        # WorkflowState 无 reducer：按执行序合并节点增量即终态（与 invoke 等价）
        for update in graph.stream(initial, config, stream_mode="updates"):
            for node, delta in update.items():
                if node == "__interrupt__":
                    interrupts = delta
                    continue
                progress(node)
                if delta:
                    final_state.update(delta)
    if interrupts:
        # info 节点挂起：翻译为 API 兼容的 needs_more_info 语义
        final_state["needs_more_info"] = True
        final_state["followup_questions"] = _extract_interrupt_payload(interrupts) or []
        final_state["status"] = "needs_more_info"
        return final_state
    return _finalize_status(final_state)


def resume_workflow(
    thread_id: str,
    answer: str,
    *,
    progress: ProgressCallback | None = None,
) -> dict[str, Any] | None:
    """从 info 中断点恢复执行；线程无挂起中断时返回 None（调用方回退全量重跑）。

    checkpoint 里的运行时句柄（settings/provider/rag）是占位标记，
    恢复时通过 Command(update=...) 重新注入当前运行时。
    """
    if not thread_id:
        return None
    graph = get_graph(use_checkpointer=True)
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = graph.get_state(config)
    if not snapshot.next:
        return None
    settings, providers, rag = build_runtime()
    runtime_update = {
        "settings": settings,
        "provider": providers[0],
        "providers": providers,
        "rag": rag,
    }
    base_state: dict[str, Any] = dict(snapshot.values or {})
    base_state.update(runtime_update)
    resume_command = Command(resume=answer, update=runtime_update)
    if progress is None:
        result = dict(graph.invoke(resume_command, config))
        result.pop("__interrupt__", None)
        final_state = result if result else base_state
    else:
        final_state = base_state
        for update in graph.stream(resume_command, config, stream_mode="updates"):
            for node, delta in update.items():
                if node == "__interrupt__":
                    continue
                progress(node)
                if delta:
                    final_state.update(delta)
    return _finalize_status(final_state)


def append_thread_state(thread_id: str, values: dict[str, Any]) -> bool:
    """人工复核结论等事后信息回写图线程状态（async 模式审计用，失败不阻断）。"""
    if not thread_id or not HAS_CHECKPOINTER:
        return False
    try:
        graph = get_graph(use_checkpointer=True)
        graph.update_state({"configurable": {"thread_id": thread_id}}, values)
        return True
    except Exception:
        logger.warning("图线程状态回写失败 thread_id=%s", thread_id, exc_info=True)
        return False


def get_pending_thread_ids(assessment_thread_ids: list[str]) -> set[str]:
    """返回仍处于挂起（等待追问）状态的 thread_id 集合（运维诊断用）。"""
    pending: set[str] = set()
    graph = get_graph(use_checkpointer=True)
    for thread_id in assessment_thread_ids:
        try:
            if graph.get_state({"configurable": {"thread_id": thread_id}}).next:
                pending.add(thread_id)
        except Exception:
            continue
    return pending
