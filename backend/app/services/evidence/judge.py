"""Determine whether retrieved regulations support each visual finding."""

from __future__ import annotations

from typing import Any

from app.services.evidence.matcher import cjk_bigrams, tokens
from app.services.evidence.schemas import (
    EvidenceJudgeResult,
    FindingEvidenceResult,
)
from app.services.rag import is_regulatory_evidence

EVIDENCE_ID_FALLBACK = "evidence"
VISUAL_PLACEHOLDER_MARKERS = (
    "待人工确认",
    "无法确认",
    "无法判断",
    "信息不足",
    "图片信息不足",
    "待补充",
    "未提供",
    "unknown",
    "n/a",
)

CATEGORY_REQUIRED_TERMS: dict[str, list[str]] = {
    "占用疏散通道": ["占用", "堵塞", "封闭", "堆放", "障碍", "锁闭"],
    "消防器材失效": [
        "灭火器",
        "消防器材",
        "消火栓",
        "压力",
        "失效",
        "过期",
        "缺失",
        "遮挡",
        "埋压",
        "圈占",
    ],
    "电气线路隐患": ["电线", "线路", "电缆", "插座", "配电", "短路", "裸露", "私拉", "破损"],
    "野外用火风险": ["用火", "明火", "焚烧", "烧荒", "燃放", "防火期", "禁止"],
    "危险化学品存储不规范": [
        "危险化学品",
        "危化品",
        "化学品",
        "储罐",
        "泄漏",
        "存储",
        "储存",
        "仓库",
        "燃气",
    ],
    "公共区域安全隐患": ["井盖", "护栏", "塌陷", "破损", "坑", "围挡", "警示"],
}


def _is_visual_placeholder(text: str) -> bool:
    lowered = (text or "").strip().lower()
    return any(marker in lowered for marker in VISUAL_PLACEHOLDER_MARKERS)


def _reliable_facts(facts: list[str]) -> list[str]:
    return [fact for fact in facts if fact and not _is_visual_placeholder(fact)]


def _has_reliable_visual(finding: dict[str, Any]) -> bool:
    facts = [str(item) for item in (finding.get("observed_facts") or [])]
    return bool(_reliable_facts(facts) or finding.get("location"))


def _evidence_score(item: dict[str, Any]) -> float:
    try:
        return min(1.0, max(0.0, float(item.get("score") or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _judge_one(
    finding: dict[str, Any],
    retrieval: list[dict[str, Any]],
) -> FindingEvidenceResult:
    finding_id = str(finding.get("finding_id") or "")
    category = str(finding.get("category") or "")
    raw_facts = [str(item) for item in (finding.get("observed_facts") or [])]
    facts = _reliable_facts(raw_facts)
    visual_ok = bool(facts) or bool(finding.get("location"))
    query_tokens = tokens(f"{category} {' '.join(facts)}")

    best_overlap = 0
    best_score = 0.0
    matched_evidence: list[dict[str, Any]] = []
    for index, item in enumerate(retrieval):
        evidence_text = str(item.get("text") or "")
        overlap = len(query_tokens & cjk_bigrams(evidence_text))
        if overlap <= 0:
            continue
        score = _evidence_score(item)
        matched_evidence.append(item)
        if overlap > best_overlap or (overlap == best_overlap and score > best_score):
            best_overlap = overlap
            best_score = score

    evidence_ids: list[str] = []
    for index, item in enumerate(matched_evidence[:4]):
        evidence_ids.append(
            str(item.get("id") or f"{EVIDENCE_ID_FALLBACK}-{index}")
        )
    unsupported: list[str] = []
    match_component = min(1.0, best_overlap / 5.0)
    support_score = round(
        min(1.0, 0.55 * match_component + 0.45 * best_score),
        3,
    )
    required_terms = CATEGORY_REQUIRED_TERMS.get(category, [])
    category_ok = bool(required_terms) and any(
        term in str(item.get("text") or "") for item in retrieval for term in required_terms
    )
    if retrieval and not category_ok and not any(
        "法规文本未覆盖" in claim for claim in unsupported
    ):
        unsupported.append("法规文本未覆盖该类隐患的禁止性行为，需人工复核")
    supported = (
        bool(retrieval)
        and category_ok
        and best_overlap >= 2
        and support_score >= 0.5
    )

    evidence_bigram_sets = [cjk_bigrams(str(item.get("text") or "")) for item in retrieval]
    for fact in facts:
        if len(fact) < 3:
            continue
        fact_tokens = cjk_bigrams(fact)
        if not any(fact_tokens & evidence_bigrams for evidence_bigrams in evidence_bigram_sets):
            unsupported.append(f"观察事实“{fact}”缺少法规依据")
    if not supported and not unsupported:
        unsupported.append(category or "未分类结论")
    if not visual_ok:
        unsupported.append(
            "视觉事实仅为占位描述，需人工确认" if raw_facts else "缺少视觉事实描述"
        )

    return FindingEvidenceResult(
        finding_id=finding_id,
        category=category,
        supported=supported,
        support_score=support_score,
        evidence_ids=evidence_ids,
        unsupported_claims=unsupported,
        visual_evidence_ok=visual_ok,
        needs_human_review=not supported or not visual_ok,
    )


def judge_evidence(
    findings: list[dict[str, Any]] | None,
    evidence: list[dict[str, Any]] | None,
) -> EvidenceJudgeResult:
    findings = findings or []
    retrieval = [
        item
        for item in (evidence or [])
        if isinstance(item, dict) and item.get("text") and is_regulatory_evidence(item)
    ]
    results = [_judge_one(finding, retrieval) for finding in findings]
    unsupported: list[str] = []
    evidence_ids: list[str] = []
    for result in results:
        unsupported.extend(result.unsupported_claims)
        evidence_ids.extend(result.evidence_ids)
    supported = bool(results) and all(
        result.supported and result.visual_evidence_ok for result in results
    )
    support_score = (
        round(sum(result.support_score for result in results) / len(results), 3)
        if results
        else 0.0
    )
    return EvidenceJudgeResult(
        supported=supported,
        support_score=support_score,
        evidence_ids=list(dict.fromkeys(evidence_ids)),
        unsupported_claims=list(dict.fromkeys(unsupported)),
        needs_human_review=not supported or any(
            result.needs_human_review for result in results
        ),
        visual_evidence_count=sum(
            1
            for finding in findings
            if _has_reliable_visual(finding)
        ),
        retrieval_evidence_count=len(retrieval),
        findings=results,
    )
