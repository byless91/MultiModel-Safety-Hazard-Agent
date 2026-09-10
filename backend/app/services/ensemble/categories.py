"""Canonical hazard category mapping shared by standardization and disagreement."""

from __future__ import annotations

from app.services.providers.mock import RULE_TEMPLATES

ALIASES = {
    "fire_exit_blocked": "占用疏散通道",
    "exit_blocked": "占用疏散通道",
    "exit_obstructed": "占用疏散通道",
    "疏散通道堵塞": "占用疏散通道",
    "疏散通道占用": "占用疏散通道",
    "消防通道堵塞": "占用疏散通道",
    "消防通道占用": "占用疏散通道",
    "extinguisher_expired": "消防器材失效",
    "fire_extinguisher": "消防器材失效",
    "灭火器失效": "消防器材失效",
    "消防器材过期": "消防器材失效",
    "electrical": "电气线路隐患",
    "wiring_exposed": "电气线路隐患",
    "电气隐患": "电气线路隐患",
    "电线私拉": "电气线路隐患",
    "线路破损": "电气线路隐患",
    "wildfire": "野外用火风险",
    "open_flame": "野外用火风险",
    "野外用火": "野外用火风险",
    "明火": "野外用火风险",
    "chemical_storage": "危险化学品存储不规范",
    "hazmat_storage": "危险化学品存储不规范",
    "危化品存储": "危险化学品存储不规范",
    "化学品存放": "危险化学品存储不规范",
    "public_area": "公共区域安全隐患",
    "manhole_damaged": "公共区域安全隐患",
    "护栏破损": "公共区域安全隐患",
    "井盖破损": "公共区域安全隐患",
}

CATEGORY_RAG_TAGS: dict[str, list[str]] = {
    "占用疏散通道": ["消防", "疏散通道", "安全出口", "消防车通道"],
    "消防器材失效": ["消防", "灭火器", "消防设施", "消火栓"],
    "电气线路隐患": ["消防", "电气", "线路", "配电箱"],
    "野外用火风险": ["森林防火", "野外用火", "林区"],
    "危险化学品存储不规范": ["安全生产", "危化品", "化学品"],
    "公共区域安全隐患": ["社区", "公共区域", "井盖", "护栏"],
}


def canonicalize_hazard_type(text: str) -> str | None:
    """Map a model hazard label to one canonical category name."""
    normalized = (text or "").strip().lower()
    if not normalized:
        return None
    if normalized in ALIASES:
        return ALIASES[normalized]
    for rule in RULE_TEMPLATES:
        if normalized == rule["category"].lower():
            return rule["category"]
    best: str | None = None
    best_score = 0.0
    for rule in RULE_TEMPLATES:
        hits = sum(1 for keyword in rule["keywords"] if keyword.lower() in normalized)
        if hits == 0:
            continue
        score = hits / max(1, len(rule["keywords"]))
        if score > best_score:
            best = rule["category"]
            best_score = score
    return best


def rag_tags_for_category(category: str | None) -> list[str]:
    return CATEGORY_RAG_TAGS.get(category or "", [])
