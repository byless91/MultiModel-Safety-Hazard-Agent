"""Versioned rule constants for the risk engine."""

from __future__ import annotations

from app.core.config import get_settings

RULE_VERSION = get_settings().risk_rule_version

CATEGORY_BASE_SCORES: dict[str, dict[str, int]] = {
    "占用疏散通道": {
        "exposure": 80,
        "hazard_source": 75,
        "consequence": 85,
        "violation": 85,
    },
    "消防器材失效": {
        "exposure": 60,
        "hazard_source": 65,
        "consequence": 75,
        "violation": 70,
    },
    "电气线路隐患": {
        "exposure": 60,
        "hazard_source": 70,
        "consequence": 80,
        "violation": 75,
    },
    "野外用火风险": {
        "exposure": 65,
        "hazard_source": 85,
        "consequence": 95,
        "violation": 90,
    },
    "危险化学品存储不规范": {
        "exposure": 70,
        "hazard_source": 90,
        "consequence": 95,
        "violation": 90,
    },
    "公共区域安全隐患": {
        "exposure": 55,
        "hazard_source": 55,
        "consequence": 60,
        "violation": 50,
    },
}

DEFAULT_BASE_SCORES = {
    "exposure": 50,
    "hazard_source": 50,
    "consequence": 55,
    "violation": 50,
}

EXPOSURE_KEYWORDS = [
    "人员密集",
    "商场",
    "学校",
    "医院",
    "宿舍",
    "地下",
    "超市",
    "电梯",
    "楼道",
    "通道",
    "住宅",
    "小区",
    "街道",
    "厂房",
    "车间",
    "避难",
]

IMMEDIATE_DANGER_KEYWORDS = [
    "明火",
    "泄漏",
    "燃气",
    "冒烟",
    "起火",
    "燃烧",
    "短路",
    "电火花",
    "异味",
    "爆炸",
    "倾倒",
]

LOW_BAND = 40
HIGH_BAND = 70

RULE_WEIGHTS = {
    "exposure": 0.30,
    "hazard_source": 0.25,
    "consequence": 0.20,
    "violation": 0.15,
    "severity_factor": 0.10,
}
