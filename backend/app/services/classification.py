"""分类服务（阶段 2）：仅做 AI 分类建议，不做完整研判

简化版工作流：
1. 输入：描述 + 图片
2. 输出：分类建议（类别、子类别、置信度）+ 推荐法规

核心区别：
- 不判定风险等级（由人工决定）
- 不需要完整的证据链和研判报告
- 只需要快速分类 + 法规推荐
"""

import json
import logging
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("safety_hazard.classification")


# 分类体系定义
CLASSIFICATION_SYSTEM = {
    "消防隐患": {
        "subcategories": ["堵塞疏散通道", "消防设施损坏", "违规用火用电", "易燃物品存放不当"],
        "keywords": ["火灾", "疏散", "灭火器", "消防栓", "烟雾", "电气", "易燃"],
    },
    "生产安全": {
        "subcategories": ["设备故障", "操作违规", "防护缺失", "高空作业隐患"],
        "keywords": ["设备", "机械", "防护", "作业", "安全帽", "安全带", "违规操作"],
    },
    "社区治理": {
        "subcategories": ["违章建筑", "环境卫生", "公共设施损坏", "违规占道"],
        "keywords": ["违建", "垃圾", "卫生", "占道", "设施", "维修", "环境"],
    },
    "其他": {
        "subcategories": ["其他安全隐患"],
        "keywords": [],
    },
}


def _extract_classification_from_analysis(analysis: dict[str, Any]) -> dict:
    """从现有的 analysis 结果中提取分类信息（兼容旧流程）"""
    # 如果有明确的类别字段
    category = analysis.get("hazard_category") or analysis.get("category")
    if category and category in CLASSIFICATION_SYSTEM:
        return {
            "category": category,
            "subcategory": analysis.get("subcategory") or CLASSIFICATION_SYSTEM[category]["subcategories"][0],
            "confidence": float(analysis.get("vision_confidence", 0.7)),
            "reasoning": analysis.get("scene_summary", ""),
        }

    # 从场景摘要推断类别
    scene = analysis.get("scene_summary", "") + " " + analysis.get("description", "")

    # 关键词匹配
    best_match = "其他"
    best_score = 0

    for cat, info in CLASSIFICATION_SYSTEM.items():
        keywords = info["keywords"]
        if not keywords:
            continue
        score = sum(1 for kw in keywords if kw in scene)
        if score > best_score:
            best_score = score
            best_match = cat

    return {
        "category": best_match,
        "subcategory": CLASSIFICATION_SYSTEM[best_match]["subcategories"][0],
        "confidence": min(0.6 + best_score * 0.1, 0.9) if best_score > 0 else 0.5,
        "reasoning": scene or "基于图片和描述的初步分析",
    }


async def classify_hazard(
    description: str,
    images: list,
    ocr_texts: list[str] | None = None,
) -> dict:
    """
    快速分类：只做分类建议，不做完整研判

    Args:
        description: 现场描述
        images: 图片列表
        ocr_texts: OCR 文本（可选）

    Returns:
        {
            "suggested_category": "消防隐患",
            "suggested_subcategory": "堵塞疏散通道",
            "confidence": 0.85,
            "reasoning": "图片显示楼道堆放大量纸箱...",
            "keywords": ["疏散", "堵塞", "楼道"]
        }
    """
    settings = get_settings()

    # 如果启用简化工作流，使用轻量级分类
    if settings.simplified_workflow:
        return await _classify_simple(description, images, ocr_texts)

    # 否则使用完整的 analyze 流程（兼容模式）
    return await _classify_with_full_analysis(description, images, ocr_texts)


async def _classify_simple(
    description: str,
    images: list,
    ocr_texts: list[str] | None = None,
) -> dict:
    """简化版分类：直接调用模型，不走完整工作流"""
    from app.services.workflow_nodes import build_runtime, initial_state, step_analyze

    settings, providers, rag = build_runtime()
    state = initial_state(
        description=description,
        images=images,
        followup_answer=None,
        followup_used=0,
        ocr_texts=ocr_texts,
        settings=settings,
        rag=rag,
        providers=providers,
    )

    try:
        # 只执行 analyze 步骤
        analyze_result = step_analyze(state)
        analysis = analyze_result.get("analysis", {})

        # 提取分类信息
        classification = _extract_classification_from_analysis(analysis)

        return {
            "suggested_category": classification["category"],
            "suggested_subcategory": classification["subcategory"],
            "confidence": classification["confidence"],
            "reasoning": classification["reasoning"],
            "keywords": analysis.get("keywords", []),
        }
    except Exception as exc:
        logger.error("简化分类失败: %s", exc, exc_info=True)
        # 兜底：基于关键词的规则分类
        return _fallback_rule_based_classification(description)


async def _classify_with_full_analysis(
    description: str,
    images: list,
    ocr_texts: list[str] | None = None,
) -> dict:
    """完整流程分类：使用现有的 analyze 节点（兼容模式）"""
    from app.services.workflow_nodes import build_runtime, initial_state, step_analyze

    settings, providers, rag = build_runtime()
    state = initial_state(
        description=description,
        images=images,
        followup_answer=None,
        followup_used=0,
        ocr_texts=ocr_texts,
        settings=settings,
        rag=rag,
        providers=providers,
    )

    analyze_result = step_analyze(state)
    analysis = analyze_result.get("analysis", {})
    classification = _extract_classification_from_analysis(analysis)

    return {
        "suggested_category": classification["category"],
        "suggested_subcategory": classification["subcategory"],
        "confidence": classification["confidence"],
        "reasoning": classification["reasoning"],
        "keywords": analysis.get("keywords", []),
    }


def _fallback_rule_based_classification(description: str) -> dict:
    """兜底：基于关键词的规则分类"""
    text = description.lower()

    for category, info in CLASSIFICATION_SYSTEM.items():
        keywords = info["keywords"]
        if not keywords:
            continue

        matched = [kw for kw in keywords if kw in text]
        if matched:
            return {
                "suggested_category": category,
                "suggested_subcategory": info["subcategories"][0],
                "confidence": min(0.5 + len(matched) * 0.1, 0.8),
                "reasoning": f"基于关键词匹配: {', '.join(matched)}",
                "keywords": matched,
            }

    # 完全无法判断
    return {
        "suggested_category": "其他",
        "suggested_subcategory": "其他安全隐患",
        "confidence": 0.3,
        "reasoning": "无法明确分类，建议人工确认",
        "keywords": [],
    }


async def recommend_regulations(
    category: str,
    subcategory: str | None,
    description: str,
    top_k: int = 5,
) -> list[dict]:
    """
    推荐相关法规条款

    Args:
        category: 隐患类别
        subcategory: 子类别
        description: 描述
        top_k: 返回数量

    Returns:
        [
            {
                "text": "法规条文",
                "source": "消防法",
                "article": "第十六条",
                "score": 0.85
            },
            ...
        ]
    """
    from app.services.rag import get_rag

    rag = get_rag()

    # 构建查询
    query_parts = [category]
    if subcategory:
        query_parts.append(subcategory)
    query_parts.append(description)
    query = " ".join(query_parts)

    # RAG 检索
    results = rag.search(query, top_k=top_k)

    # 格式化结果
    regulations = []
    for item in results:
        regulations.append({
            "text": item.get("text", ""),
            "source": item.get("source", ""),
            "article": item.get("article", ""),
            "score": item.get("score", 0.0),
        })

    return regulations
