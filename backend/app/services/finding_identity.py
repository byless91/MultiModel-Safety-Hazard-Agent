"""Stable concrete finding identities and conservative views of legacy IDs."""

import hashlib
import json
import math
from collections import Counter
from copy import deepcopy
from typing import Any

LEGACY_IDENTITY_WARNING = "历史隐患标识缺失或重复，无法可靠恢复逐项证据对应关系，需人工核查"


def location_signature(location: dict[str, Any] | None) -> tuple:
    if not isinstance(location, dict):
        return ()
    raw = location.get("bbox")
    bbox = ()
    if (isinstance(raw, (list, tuple)) and len(raw) == 4
            and all(type(value) in (int, float) and math.isfinite(value) for value in raw)):
        bbox = tuple(float(value) or 0.0 for value in raw)
    image = str(location.get("image_id") or "").strip()
    text = str(location.get("location_text") or "").strip()
    return (image, bbox, text) if image or bbox or text else ()


def finding_identifier(category: str, identity: Any) -> str:
    encoded = json.dumps([category, identity], ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return "finding-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def ambiguous_positions(findings: list[dict]) -> set[int]:
    counts = Counter(str(item.get("finding_id") or "") for item in findings)
    return {index for index, item in enumerate(findings)
            if not item.get("finding_id") or counts[str(item["finding_id"])] > 1}


def ensure_unique_finding_ids(findings: list[dict]) -> list[dict]:
    """Preserve valid IDs; repair missing/duplicate IDs only on a copied view."""
    result = deepcopy(findings)
    ambiguous = ambiguous_positions(result)
    used = {str(item["finding_id"]) for index, item in enumerate(result) if index not in ambiguous}
    for index, item in enumerate(result):
        if index not in ambiguous:
            continue
        locations = item.get("locations") or [item.get("location")]
        signatures = sorted([location_signature(location) for location in locations], key=str)
        identity = ["legacy", signatures, sorted(str(fact) for fact in (item.get("observed_facts") or [])),
                    str(item.get("description") or "")]
        base = finding_identifier(str(item.get("category") or ""), identity)
        identifier, suffix = base, 1
        while identifier in used:
            suffix += 1
            identifier = f"{base}-{suffix}"
        item["finding_id"] = identifier
        used.add(identifier)
    return result


def legacy_evidence_view(
    findings: list[dict], evidence_judge: dict | None,
) -> tuple[list[dict], dict | None, list[str]]:
    """Unknown old associations are not reconstructed or persisted as support."""
    ambiguous = ambiguous_positions(findings)
    if not ambiguous:
        return findings, evidence_judge, []
    result = ensure_unique_finding_ids(findings)
    judge = deepcopy(evidence_judge or {})
    old_statuses = {item.get("finding_id"): item for item in judge.get("findings", [])}
    statuses = []
    for index, item in enumerate(result):
        if index in ambiguous:
            claims = list(item.get("unsupported_claims") or [])
            if LEGACY_IDENTITY_WARNING not in claims:
                claims.append(LEGACY_IDENTITY_WARNING)
            item.update(evidence_status="pending", evidence_ids=[], support_score=None, unsupported_claims=claims)
            statuses.append({
                "finding_id": item["finding_id"], "category": item.get("category", ""),
                "supported": False, "support_score": 0.0, "evidence_ids": [], "unsupported_claims": claims,
                "visual_evidence_ok": False, "needs_human_review": True, "identity_ambiguous": True,
            })
        elif item.get("finding_id") in old_statuses:
            statuses.append(old_statuses[item["finding_id"]])
    claims = list(judge.get("unsupported_claims") or [])
    if LEGACY_IDENTITY_WARNING not in claims:
        claims.append(LEGACY_IDENTITY_WARNING)
    judge.update(supported=False, needs_human_review=True, support_score=0.0, findings=statuses,
                 unsupported_claims=claims, evidence_ids=list(dict.fromkeys(
                     evidence_id for status in statuses for evidence_id in status.get("evidence_ids", []))),
                 identity_ambiguous=True)
    return result, judge, [LEGACY_IDENTITY_WARNING]
