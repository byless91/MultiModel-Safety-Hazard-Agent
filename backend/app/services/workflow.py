"""研判工作流入口：优先 LangGraph 图，未安装时回退函数式流程。

节点实现共享自 workflow_nodes.py；本文件只负责编排、兜底语义与指标埋点。
progress 回调用于异步任务（job_runner）逐步上报节点进度。
"""

import time
from collections.abc import Callable
from typing import Any

from app.core import metrics
from app.services.human_review import decide_human_review
from app.services.langgraph_flow import HAS_LANGGRAPH, run_langgraph
from app.services.workflow_nodes import (
    build_runtime,
    initial_state,
    step_analyze,
    step_evidence,
    step_generate,
    step_info,
    step_judge,
    step_refine,
    step_retrieve,
)

ProgressCallback = Callable[[str], None]


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
    progress: ProgressCallback | None = None,
    thread_id: str | None = None,
    use_checkpointer: bool = False,
    entry_mode: str = "assessment",
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        if entry_mode in {"classification", "manual"}:
            from app.services.classification import run_classification

            state = run_classification(description, images, ocr_texts=ocr_texts, manual=entry_mode == "manual",
                                       rag=rag, provider=providers[0] if providers else None, progress=progress)
        elif HAS_LANGGRAPH:
            state = run_langgraph(
                description,
                images,
                followup_answer,
                followup_used,
                ocr_texts=ocr_texts,
                settings=settings,
                rag=rag,
                providers=providers,
                progress=progress,
                thread_id=thread_id,
                use_checkpointer=use_checkpointer,
            )
        else:
            state = run_functional(
                description,
                images,
                followup_answer,
                followup_used,
                ocr_texts=ocr_texts,
                settings=settings,
                rag=rag,
                providers=providers,
                progress=progress,
            )
    except Exception:
        metrics.WORKFLOW_TOTAL.labels(status="failed").inc()
        raise
    metrics.WORKFLOW_DURATION.observe(time.perf_counter() - started)
    metrics.WORKFLOW_TOTAL.labels(status=str(state.get("status") or "unknown")).inc()
    return state


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
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    settings, providers, rag = build_runtime(
        settings=settings, rag=rag, providers=providers
    )
    state = initial_state(
        description,
        images,
        followup_answer,
        followup_used,
        ocr_texts,
        settings,
        rag,
        providers,
    )
    if progress:
        progress("analyze")
    state.update(step_analyze(state))
    state.update(step_info(state))
    if state.get("needs_more_info"):
        state["status"] = "needs_more_info"
        return state
    if progress:
        progress("retrieve")
    state.update(step_retrieve(state))
    if progress:
        progress("refine")
    state.update(step_refine(state))
    if progress:
        progress("judge")
    state.update(step_judge(state))
    if progress:
        progress("evidence")
    state.update(step_evidence(state))
    if progress:
        progress("generate")
    state.update(step_generate(state))
    # 与 LangGraph 路径的已知差异：函数式路径在复核判定前对置信度取 3 位小数
    state["confidence"] = round(state["confidence"], 3)
    review = decide_human_review(state)
    state["review_reasons"] = review.review_reasons
    state["human_review"] = review.model_dump()
    state["status"] = (
        "awaiting_human_review" if review.need_human_review else "completed"
    )
    return state
