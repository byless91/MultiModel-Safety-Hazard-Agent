"""B1/WP5.5：两条执行路径（LangGraph 图 / 函数式回退）结果一致性。

节点实现已收敛到 workflow_nodes.py，本测试防止未来任一路径单独改动
造成两条路径结果漂移。
"""

import pytest

from app.services import langgraph_flow, workflow

COMPLETED_CASE = "小区楼道堆放纸箱杂物，堵塞疏散通道，通行明显受阻"
NEEDS_INFO_CASE = "现场有异常"


def test_paths_agree_on_completed_case():
    if not langgraph_flow.HAS_LANGGRAPH:
        pytest.skip("LangGraph 未安装，无路径对比意义")
    graph_state = langgraph_flow.run_langgraph(COMPLETED_CASE, [])
    functional_state = workflow.run_functional(COMPLETED_CASE, [])
    assert graph_state["status"] == functional_state["status"]
    assert graph_state["hazard_category"] == functional_state["hazard_category"]
    assert graph_state.get("risk_level") == functional_state.get("risk_level")
    # 函数式路径会 round(confidence, 3)，对比时对齐精度
    assert round(graph_state["confidence"], 3) == round(functional_state["confidence"], 3)
    assert graph_state["scene_summary"] == functional_state["scene_summary"]
    assert graph_state["multi_model"]["ensemble_mode"] == (
        functional_state["multi_model"]["ensemble_mode"]
    )
    graph_findings = graph_state["ensemble_judge"]["final_findings"]
    functional_findings = functional_state["ensemble_judge"]["final_findings"]
    assert [f["finding_id"] for f in graph_findings] == [
        f["finding_id"] for f in functional_findings
    ]
    assert [f["category"] for f in graph_findings] == [
        f["category"] for f in functional_findings
    ]
    assert [e["text"] for e in graph_state["evidence"]] == [
        e["text"] for e in functional_state["evidence"]
    ]
    assert graph_state["review_reasons"] == functional_state["review_reasons"]


def test_paths_agree_on_needs_more_info_case():
    if not langgraph_flow.HAS_LANGGRAPH:
        pytest.skip("LangGraph 未安装，无路径对比意义")
    graph_state = langgraph_flow.run_langgraph(NEEDS_INFO_CASE, [])
    functional_state = workflow.run_functional(NEEDS_INFO_CASE, [])
    assert graph_state["status"] == "needs_more_info"
    assert functional_state["status"] == "needs_more_info"
    assert graph_state["followup_questions"] == functional_state["followup_questions"]
    assert graph_state["followup_used"] == functional_state["followup_used"] == 0


def test_paths_agree_on_followup_case():
    if not langgraph_flow.HAS_LANGGRAPH:
        pytest.skip("LangGraph 未安装，无路径对比意义")
    graph_state = langgraph_flow.run_langgraph(
        NEEDS_INFO_CASE, [], followup_answer="楼道堆放了大量纸箱，影响疏散通道通行"
    )
    functional_state = workflow.run_functional(
        NEEDS_INFO_CASE, [], followup_answer="楼道堆放了大量纸箱，影响疏散通道通行"
    )
    assert graph_state["status"] == functional_state["status"]
    assert graph_state["hazard_category"] == functional_state["hazard_category"]
    assert round(graph_state["confidence"], 3) == round(functional_state["confidence"], 3)
