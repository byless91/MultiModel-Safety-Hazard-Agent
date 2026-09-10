"""Rectification state machine with traceable transition history."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


RECTIFICATION_STATUSES = [
    "open",
    "assigned",
    "rectifying",
    "pending_verification",
    "verified",
    "closed",
]

RECTIFICATION_STATUS_LABELS = {
    "open": "待分派",
    "assigned": "已分派",
    "rectifying": "整改中",
    "pending_verification": "待验证",
    "verified": "已验证",
    "closed": "已关闭",
}

STATUS_ALIASES = {
    None: "open",
    "": "open",
    "pending": "open",
    "under_review": "pending_verification",
    "resolved": "verified",
}

ALLOWED_TRANSITIONS = {
    "open": ["assigned", "rectifying"],
    "assigned": ["rectifying", "open"],
    "rectifying": ["pending_verification", "open", "assigned"],
    "pending_verification": ["verified", "rectifying"],
    "verified": ["closed", "rectifying"],
    "closed": ["open"],
}

ACTION_LABELS = {
    ("open", "assigned"): "分派整改",
    ("open", "rectifying"): "开始整改",
    ("assigned", "rectifying"): "开始整改",
    ("assigned", "open"): "退回待分派",
    ("rectifying", "pending_verification"): "提交整改照片并 AI 比对",
    ("rectifying", "open"): "重新打开",
    ("rectifying", "assigned"): "退回已分派",
    ("pending_verification", "verified"): "人工确认整改完成",
    ("pending_verification", "rectifying"): "退回整改",
    ("verified", "closed"): "关闭工单",
    ("verified", "rectifying"): "退回整改",
    ("closed", "open"): "重新打开",
}


class RectificationTransitionError(ValueError):
    pass


def normalize_rectification_status(value: Any) -> str:
    if value in STATUS_ALIASES:
        return STATUS_ALIASES[value]
    normalized = str(value or "open").strip()
    return normalized if normalized in RECTIFICATION_STATUSES else "open"


def next_rectification_states(value: Any) -> list[str]:
    current = normalize_rectification_status(value)
    return list(ALLOWED_TRANSITIONS.get(current, []))


def rectification_state_label(value: Any) -> str:
    return RECTIFICATION_STATUS_LABELS.get(
        normalize_rectification_status(value),
        "未知状态",
    )


def _parse_meta(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def rectification_history(item: Any) -> list[dict[str, Any]]:
    meta = _parse_meta(getattr(item, "rectification_meta_json", None))
    history = meta.get("history") or []
    return history if isinstance(history, list) else []


def append_rectification_history(
    item: Any,
    *,
    from_status: str,
    to_status: str,
    note: str | None = None,
    by: str | None = None,
) -> None:
    meta = _parse_meta(getattr(item, "rectification_meta_json", None))
    history = meta.setdefault("history", [])
    if not isinstance(history, list):
        history = []
        meta["history"] = history
    action = ACTION_LABELS.get((from_status, to_status), f"{from_status}->{to_status}")
    history.append(
        {
            "action": action,
            "from_status": from_status,
            "to_status": to_status,
            "note": note or "",
            "by": by or "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    meta["current_status"] = to_status
    item.rectification_meta_json = json.dumps(meta, ensure_ascii=False)


def transition_rectification(
    item: Any,
    target: Any,
    *,
    note: str | None = None,
    by: str | None = None,
) -> str:
    """Strict single-step transition between two adjacent states."""
    current = normalize_rectification_status(getattr(item, "rectification_status", None))
    normalized_target = normalize_rectification_status(target)
    if current == normalized_target:
        return current
    if normalized_target not in ALLOWED_TRANSITIONS.get(current, []):
        raise RectificationTransitionError(
            f"非法整改状态流转：{current} -> {normalized_target}"
        )
    append_rectification_history(
        item,
        from_status=current,
        to_status=normalized_target,
        note=note,
        by=by,
    )
    item.rectification_status = normalized_target
    return normalized_target


def walk_rectification(
    item: Any,
    targets: list[str],
    *,
    note: str | None = None,
    by: str | None = None,
) -> str:
    """Apply several adjacent transitions in order, e.g. photo submission."""
    current = normalize_rectification_status(getattr(item, "rectification_status", None))
    for target in targets:
        current = transition_rectification(item, target, note=note, by=by)
    return current


def submit_rectification_photos(
    item: Any,
    *,
    note: str | None = None,
    by: str | None = None,
) -> str:
    """Move an open/assigned/rectifying case into pending_verification."""
    current = normalize_rectification_status(getattr(item, "rectification_status", None))
    if current == "pending_verification":
        return current
    paths = {
        "open": ["assigned", "rectifying", "pending_verification"],
        "assigned": ["rectifying", "pending_verification"],
        "rectifying": ["pending_verification"],
    }
    path = paths.get(current)
    if path is None:
        raise RectificationTransitionError(
            f"当前整改状态不允许提交整改照片：{current}"
        )
    return walk_rectification(item, path, note=note, by=by)
