"""简化工作流（阶段 2）：分类 + 法规推荐

替代原有的复杂研判流程（analyze → info → retrieve → refine → judge → evidence → generate）
简化为：classify → recommend_regulations

用于快速录入场景：巡查员拍照 → AI 分类建议 → 推荐法规 → 人工确认
"""

import logging
from typing import Any

from app.services.classification import classify_hazard, recommend_regulations

logger = logging.getLogger("safety_hazard.simple_workflow")


async def run_classification_workflow(
    description: str,
    images: list,
    ocr_texts: list[str] | None = None,
) -> dict:
    """
    简化工作流：分类 + 法规推荐

    Args:
        description: 现场描述
        images: 图片列表
        ocr_texts: OCR 文本（可选）

    Returns:
        {
            "classification": {
                "suggested_category": "消防隐患",
                "suggested_subcategory": "堵塞疏散通道",
                "confidence": 0.85,
                "reasoning": "...",
                "keywords": [...]
            },
            "recommended_regulations": [
                {
                    "text": "法规条文",
                    "source": "消防法",
                    "article": "第十六条",
                    "score": 0.85
                },
                ...
            ],
            "status": "classification_completed"
        }
    """
    try:
        # 1. 分类
        classification = await classify_hazard(description, images, ocr_texts)

        # 2. 推荐法规
        category = classification["suggested_category"]
        subcategory = classification.get("suggested_subcategory")
        regulations = await recommend_regulations(
            category=category,
            subcategory=subcategory,
            description=description,
            top_k=5,
        )

        return {
            "classification": classification,
            "recommended_regulations": regulations,
            "status": "classification_completed",
        }

    except Exception as exc:
        logger.error("简化工作流失败: %s", exc, exc_info=True)
        return {
            "classification": {
                "suggested_category": "其他",
                "suggested_subcategory": "其他安全隐患",
                "confidence": 0.0,
                "reasoning": f"分类失败: {str(exc)[:200]}",
                "keywords": [],
            },
            "recommended_regulations": [],
            "status": "failed",
            "error": str(exc)[:500],
        }


# 保留兼容接口：与原有 workflow.run_workflow 签名一致
async def run_workflow(
    description: str,
    images: list,
    followup_answer: str | None = None,
    followup_used: int = 0,
    *,
    ocr_texts: list[str] | None = None,
    settings: Any | None = None,
    rag: Any | None = None,
    providers: list | None = None,
    progress: Any | None = None,
    thread_id: str | None = None,
    use_checkpointer: bool = False,
) -> dict[str, Any]:
    """
    兼容接口：与原有 workflow.run_workflow 签名一致

    如果启用简化工作流，使用新流程；否则回退到原有流程
    """
    from app.core.config import get_settings

    settings = settings or get_settings()

    # 如果启用简化工作流
    if settings.simplified_workflow:
        logger.info("使用简化工作流")
        if progress:
            progress("classify")

        result = await run_classification_workflow(description, images, ocr_texts)

        # 适配返回格式（与原有 workflow 返回格式一致）
        classification = result["classification"]
        return {
            "description": description,
            "images": images,
            "status": result["status"],
            "scene_summary": classification.get("reasoning", ""),
            "hazard_category": classification.get("suggested_category"),
            "confidence": classification.get("confidence", 0.0),
            "keywords": classification.get("keywords", []),
            # 新增字段
            "suggested_category": classification.get("suggested_category"),
            "suggested_subcategory": classification.get("suggested_subcategory"),
            "classification_confidence": classification.get("confidence"),
            "recommended_regulations": result.get("recommended_regulations", []),
            # 空字段（简化流程不生成）
            "risk_level": None,
            "conclusion": None,
            "evidence": [],
            "report": {},
        }

    # 否则使用原有的完整研判流程
    logger.info("使用完整研判流程")
    from app.services import workflow as original_workflow

    return original_workflow.run_workflow(
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
