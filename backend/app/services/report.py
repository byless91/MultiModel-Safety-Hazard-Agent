from typing import Any


def build_report(state: dict[str, Any]) -> dict[str, Any]:
    category = state.get("hazard_category") or "待确认隐患"
    level = state.get("risk_level") or 3
    confidence = state.get("confidence") or 0.0
    evidence = state.get("evidence", [])
    analysis = state.get("analysis", {})
    rule = analysis.get("rule", {}) or {}

    immediate = rule.get("actions") or ["采取隔离与警示措施", "联系责任单位核实", "补充信息后复检"]
    if level == 1:
        deadline = "立即处置并同步上报"
    elif level == 2:
        deadline = "限期整改"
    else:
        deadline = "列入计划整改"

    long_term = [
        "建立隐患台账并明确整改责任人与期限",
        "整改完成后回传照片复查，形成闭环",
        "纳入日常巡检计划，防止同类问题复发",
    ]

    work_order = {
        "title": f"{category}隐患整改工单",
        "category": category,
        "level": f"{level} 级",
        "deadline": deadline,
        "location": "由巡查人员填写具体位置",
        "items": immediate,
        "acceptance": "整改后复查并上传整改照片",
        "source_note": "AI 辅助生成，需人工确认",
    }

    summary = f"现场照片与描述综合分析，疑似存在“{category}”类隐患，建议按 {level} 级进行处置。"
    briefing = (
        f"巡查发现疑似{category}类隐患。系统建议立即采取："
        + "；".join(immediate[:2])
        + "。最终结论需巡查人员现场确认后上报。"
    )

    return {
        "summary": summary,
        "briefing": briefing,
        "category": category,
        "level": level,
        "confidence": confidence,
        "evidence_count": len(evidence),
        "legal_basis": [
            {
                "source": item.get("source", "未标注来源"),
                "snippet": item.get("text", ""),
                "version": item.get("version", ""),
                "tags": item.get("tags", []),
                "score": item.get("score", 0),
            }
            for item in evidence
        ],
        "immediate_actions": immediate,
        "long_term_actions": long_term,
        "work_order": work_order,
        "disclaimer": "本报告由 AI 辅助生成，仅供研判参考，需人工确认后使用。",
    }

