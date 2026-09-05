from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings, get_settings

VISION_PROMPT = (
    "你是基层安全隐患研判助手。请分析现场照片和文字描述，只输出 JSON，"
    "字段包括：scene_summary（场景概述）、observations（观察到的现象数组）、"
    "hazard_hints（可能的隐患类型数组）、keywords（关键特征数组）、"
    "vision_confidence（0到1的视觉置信度）。如果图片信息不足，请如实标注低置信度。"
)

COMPARE_PROMPT = (
    "你是基层安全隐患整改验收助手。请对比整改前与整改后的照片，结合整改说明，"
    "只输出 JSON，字段包括：completion_score（0到1的整改完成度）、"
    "status_hint（resolved 或 under_review）、summary（简要结论）、"
    "issues（仍存在的问题数组）。如果信息不足，请降低完成度并说明原因。"
)


@dataclass
class ImageInput:
    filename: str
    path: Path
    mime_type: str | None = None


RULE_TEMPLATES = [
    {
        "category": "占用疏散通道",
        "keywords": [
            "疏散通道",
            "楼道",
            "堆物",
            "纸箱",
            "杂物",
            "安全出口",
            "堵塞",
            "占用",
            "消防通道",
            "消防车通道",
            "通道口",
            "疏散",
            "堆放",
            "通行",
            "受阻",
        ],
        "level": 1,
        "followups": ["杂物是否影响人员通行或安全出口？", "该位置是否为疏散通道或安全出口附近？"],
        "actions": ["立即清理疏散通道，保障通行宽度", "整改期间设置警示并进行值守", "同步上报属地安全管理部门"],
    },
    {
        "category": "消防器材失效",
        "keywords": [
            "灭火器",
            "消防器材",
            "过期",
            "压力表",
            "消防设施",
            "缺失",
            "消防栓",
            "消火栓",
            "水带",
            "水枪",
            "器材",
            "挡住",
            "遮挡",
        ],
        "level": 2,
        "followups": ["灭火器压力表指针是否在绿色区域？", "是否已过检修有效期？"],
        "actions": ["停用并更换失效器材", "补充缺失器材到规定点位", "建立消防器材检查台账"],
    },
    {
        "category": "电气线路隐患",
        "keywords": [
            "电线",
            "线路",
            "插座",
            "私拉",
            "裸露",
            "破损",
            "电箱",
            "超负荷",
            "配电箱",
            "电表箱",
            "配电房",
            "线缆",
            "外露",
            "飞线",
        ],
        "level": 2,
        "followups": ["线路破损处是否有带电风险？", "是否存在私拉乱接或超负荷使用？"],
        "actions": ["断电后由持证电工排查", "拆除私拉乱接线路", "规范敷设并做好绝缘防护"],
    },
    {
        "category": "野外用火风险",
        "keywords": ["明火", "野外用火", "烧荒", "祭祀", "烟头", "林区", "秸秆"],
        "level": 1,
        "followups": ["是否位于林区或防火期内？", "用火是否已取得许可？"],
        "actions": ["立即制止并稳妥扑灭", "上报属地管理部门", "设置警示标识并加强巡查"],
    },
    {
        "category": "危险化学品存储不规范",
        "keywords": ["化学品", "危化品", "油桶", "燃气", "储罐", "泄漏", "仓库"],
        "level": 1,
        "followups": ["是否有泄漏或异味？", "存放区域是否远离火源？"],
        "actions": ["隔离风险区域并禁止无关人员进入", "专业人员处置泄漏", "核查存储资质与条件"],
    },
    {
        "category": "公共区域安全隐患",
        "keywords": ["井盖", "护栏", "塌陷", "破损", "坑洞", "公共区域", "倾斜", "掉落"],
        "level": 3,
        "followups": ["破损位置是否处于行人主要路径？", "是否有坠落或绊倒风险？"],
        "actions": ["设置临时警示围挡", "联系责任单位限期修复", "修复后复查闭环"],
    },
]


def hash_embed(texts: list[str], dim: int = 256) -> list[list[float]]:
    """Deterministic hash embedding used by the mock provider and as fallback."""
    vectors = []
    for text in texts:
        vec = [0.0] * dim
        for token in re.findall(r"[\u4e00-\u9fff]{2,6}|[a-zA-Z0-9_]+", text):
            digest = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            vec[digest % dim] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        vectors.append([round(x / norm, 6) for x in vec])
    return vectors


class BaseProvider:
    name = "base"

    def analyze(self, images: list[ImageInput], text: str) -> dict[str, Any]:
        raise NotImplementedError

    def complete(self, system: str, user: str) -> dict[str, Any]:
        raise NotImplementedError

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def compare(
        self,
        originals: list[ImageInput],
        rectifications: list[ImageInput],
        note: str = "",
    ) -> dict[str, Any]:
        raise NotImplementedError


class MockProvider(BaseProvider):
    name = "mock"

    def analyze(self, images: list[ImageInput], text: str) -> dict[str, Any]:
        text_lower = (text or "").lower()
        best = None
        best_score = 0.0
        for rule in RULE_TEMPLATES:
            hits = sum(1 for kw in rule["keywords"] if kw.lower() in text_lower)
            score = hits / max(1, len(rule["keywords"]))
            if hits > 0 and score > best_score:
                best = rule
                best_score = score
        matched_rule = best is not None
        if best is None:
            best = {
                "category": "待进一步确认的隐患",
                "keywords": [],
                "level": 3,
                "followups": ["请补充隐患位置、危险程度和现场环境。"],
                "actions": ["先采取隔离与警示措施", "联系责任单位核实情况", "补充照片和描述后重新研判"],
            }
            best_score = 0.15
        detail_bonus = 0.1 if len((text or "").strip()) > 10 else 0.0
        if matched_rule:
            vision_conf = min(0.95, 0.55 + best_score * 1.5 + detail_bonus)
        else:
            vision_conf = min(0.5, 0.35 + detail_bonus)
        matched = [kw for kw in best["keywords"] if kw in text_lower]
        return {
            "scene_summary": f"根据描述判断，现场疑似涉及{best['category']}相关场景。",
            "observations": matched or ["照片特征待人工确认"],
            "hazard_hints": [best["category"]],
            "keywords": matched,
            "rule": best,
            "rule_score": round(best_score, 3),
            "vision_confidence": round(vision_conf, 3),
        }

    def complete(self, system: str, user: str) -> dict[str, Any]:
        return {"summary": user[:200], "confidence": 0.7}

    def embed(self, texts: list[str]) -> list[list[float]]:
        return hash_embed(texts)

    def compare(
        self,
        originals: list[ImageInput],
        rectifications: list[ImageInput],
        note: str = "",
    ) -> dict[str, Any]:
        positive_keywords = ["清理", "整改", "更换", "修复", "完成", "已", "拆除", "补齐", "规范", "恢复", "移除"]
        hits = sum(1 for keyword in positive_keywords if keyword in note)
        score = 0.25
        reasons = []
        if rectifications:
            score += 0.35
            reasons.append("已收到整改后照片")
        if hits:
            score += min(0.3, hits * 0.12)
            reasons.append("整改说明包含完成性关键词")
        if not originals:
            score = min(score, 0.55)
            reasons.append("缺少整改前照片，完成度置信度受限")
        score = round(min(0.95, score), 3)
        status_hint = "resolved" if score >= 0.8 else "under_review"
        return {
            "completion_score": score,
            "status_hint": status_hint,
            "summary": f"Mock 比对完成，整改完成度 {score:.0%}。",
            "issues": ["建议人工复核整改现场"] if status_hint == "under_review" else [],
            "reasons": reasons,
        }


class OpenAICompatibleProvider(BaseProvider):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        vision_model: str,
        text_model: str,
        embedding_model: str,
        name: str = "openai-compatible",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.vision_model = vision_model
        self.text_model = text_model
        self.embedding_model = embedding_model
        self.name = name

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        with httpx.Client(base_url=self.base_url, headers=headers, timeout=60.0) as client:
            response = client.post(path, json=payload)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {"content": parsed}
        except json.JSONDecodeError:
            return {"content": content}

    def analyze(self, images: list[ImageInput], text: str) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": f"{VISION_PROMPT}\n文字描述：{text}"}]
        for image in images:
            b64 = base64.b64encode(image.path.read_bytes()).decode("ascii")
            mime = image.mime_type or "image/jpeg"
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        payload = {
            "model": self.vision_model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.2,
        }
        data = self._post("/chat/completions", payload)
        result = self._parse_json(data["choices"][0]["message"]["content"])
        result.setdefault("vision_confidence", 0.8)
        result.setdefault("hazard_hints", [])
        result.setdefault("scene_summary", result.get("scene_summary") or text[:200])
        if "rule" not in result:
            result["rule"] = {}
        return result

    def complete(self, system: str, user: str) -> dict[str, Any]:
        payload = {
            "model": self.text_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        data = self._post("/chat/completions", payload)
        return self._parse_json(data["choices"][0]["message"]["content"])

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        batch_size = 10
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            data = self._post("/embeddings", {"model": self.embedding_model, "input": batch})
            vectors.extend(item["embedding"] for item in data["data"])
        return vectors

    def compare(
        self,
        originals: list[ImageInput],
        rectifications: list[ImageInput],
        note: str = "",
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = [
            {"type": "text", "text": f"{COMPARE_PROMPT}\n整改说明：{note}"}
        ]
        for image in originals:
            content.append(self._image_content(image))
        for image in rectifications:
            content.append(self._image_content(image))
        payload = {
            "model": self.vision_model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.2,
        }
        data = self._post("/chat/completions", payload)
        result = self._parse_json(data["choices"][0]["message"]["content"])
        try:
            result["completion_score"] = round(min(1.0, max(0.0, float(result.get("completion_score", 0.5)))), 3)
        except (TypeError, ValueError):
            result["completion_score"] = 0.5
        result.setdefault("status_hint", "resolved" if result["completion_score"] >= 0.8 else "under_review")
        result.setdefault("summary", "视觉模型已完成整改前后对比。")
        result.setdefault("issues", [])
        return result

    def _image_content(self, image: ImageInput) -> dict[str, Any]:
        b64 = base64.b64encode(image.path.read_bytes()).decode("ascii")
        mime = image.mime_type or "image/jpeg"
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


_provider: BaseProvider | None = None


def build_provider(settings: Settings) -> BaseProvider:
    if settings.active_provider != "openai":
        return MockProvider()
    if settings.dashscope_api_key:
        return OpenAICompatibleProvider(
            base_url=settings.dashscope_base_url,
            api_key=settings.dashscope_api_key,
            vision_model=settings.vision_model,
            text_model=settings.text_model,
            embedding_model=settings.embedding_model,
            name="dashscope",
        )
    if settings.zhipu_api_key:
        return OpenAICompatibleProvider(
            base_url=settings.zhipu_base_url,
            api_key=settings.zhipu_api_key,
            vision_model=settings.vision_model,
            text_model=settings.text_model,
            embedding_model=settings.embedding_model,
            name="zhipu",
        )
    return MockProvider()


def get_provider() -> BaseProvider:
    global _provider
    if _provider is None:
        _provider = build_provider(get_settings())
    return _provider


def reset_provider() -> None:
    global _provider
    _provider = None
