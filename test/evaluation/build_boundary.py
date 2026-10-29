"""Deterministic original geometric fixtures; never represent field photographs."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
VERSION = "r6-synthetic-v1"


def build() -> None:
    directory = HERE / "images"
    directory.mkdir(exist_ok=True)
    scenes = [
        ("fire", "消防", "占用疏散通道", "商场安全出口被货物堵住，出口门无法打开", 1),
        ("factory", "生产安全", "电气线路隐患", "车间电线破损裸露，插座超负荷发热", 1),
        ("community", "社区", "公共区域安全隐患", "小区道路井盖缺失，行人可能坠落", 2),
        ("forest", "林区", "野外用火风险", "林区有人生火，周边有大量干草和落叶", 1),
    ]
    rows = []
    for slug, scenario, category, text, severity in scenes:
        for hazardous in (True, False):
            name = f"{slug}-{'hazard' if hazardous else 'safe'}"
            image = Image.new("RGB", (320, 200), "#e6edf1")
            draw = ImageDraw.Draw(image)
            draw.text((12, 8), f"SYNTHETIC / {slug.upper()} / {'HAZARD' if hazardous else 'CLEAR'}", fill="black")
            draw.rectangle((20, 45, 300, 180), outline="#415363", width=3)
            if slug == "fire":
                draw.rectangle((120, 48, 200, 180), fill="#40856f")
                if hazardous:
                    draw.rectangle((100, 110, 225, 175), fill="#bb6445")
            elif slug == "factory":
                draw.line(
                    [(35, 90), (100, 150), (180, 70), (280, 140)], fill="#a83c32" if hazardous else "#40856f", width=8
                )
                if hazardous:
                    draw.ellipse((165, 55, 200, 90), fill="#e1b653")
            elif slug == "community":
                draw.ellipse((115, 75, 205, 155), fill="#212a32" if hazardous else "#7c8b96")
            else:
                for x in (55, 120, 220, 270):
                    draw.polygon([(x, 58), (x - 20, 135), (x + 20, 135)], fill="#40856f")
                if hazardous:
                    draw.polygon([(150, 170), (175, 95), (200, 170)], fill="#d47c34")
            image.save(directory / f"{name}.png")
            rows.append(
                make_row(
                    name,
                    scenario,
                    text if hazardous else f"{scenario}合成负例：图中通道和设施完整，无目标隐患",
                    category if hazardous else "无隐患",
                    severity if hazardous else 3,
                    hazardous,
                    ["hazard" if hazardous else "safe_negative", slug],
                )
            )
    # Additional stress inputs have known authored specifications, not human labels.
    image = Image.open(directory / "fire-hazard.png").resize((8, 5)).resize((320, 200))
    image.filter(ImageFilter.GaussianBlur(12)).save(directory / "low-quality.png")
    rows.append(
        make_row(
            "low-quality",
            "消防",
            "合成低质量图，现场目标模糊，无法确认，请要求补充清晰照片",
            "占用疏散通道",
            1,
            True,
            ["low_quality"],
            abstain=True,
        )
    )
    image = Image.open(directory / "fire-hazard.png")
    draw = ImageDraw.Draw(image)
    draw.line([(30, 60), (60, 95), (30, 120)], fill="#a83c32", width=8)
    image.save(directory / "multi-hazard.png")
    rows.append(
        make_row(
            "multi-hazard",
            "消防",
            "安全出口被堆物堵塞，左侧电线破损裸露，存在两处隐患",
            "占用疏散通道",
            1,
            True,
            ["multiple_hazards"],
        )
    )
    rows.append(
        make_row(
            "contradiction",
            "消防",
            "用户声称没有隐患，须以图片中被堵住的安全出口为准",
            "占用疏散通道",
            1,
            True,
            ["image_text_conflict"],
            image="fire-hazard",
        )
    )
    rows.append(
        make_row(
            "unsupported",
            "生产安全",
            "合成生产现场存在化学品混放，当前开发节选语料无对应条款，需补充证据",
            "危险化学品存储不规范",
            2,
            True,
            ["insufficient_evidence"],
            image="factory-hazard",
            supported=False,
        )
    )
    (HERE / "cases.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    (HERE / "dataset_meta.json").write_text(
        json.dumps(
            {
                "dataset_version": VERSION,
                "schema_version": "2.0",
                "title": "R6 合成图片工程边界集（非真实现场）",
                "case_count": len(rows),
                "created_at": "2026-10-29",
                "real_acceptance_status": "pending_real_images_and_human_labels",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def make_row(name, scenario, text, category, severity, hazard, tags, *, abstain=False, image=None, supported=None):
    return {
        "id": f"syn-{name}",
        "schema_version": "2.0",
        "dataset_version": VERSION,
        "scenario": scenario,
        "description": text,
        "expected_category": category,
        "expected_level": severity,
        "ground_truth_hazard_present": hazard,
        "image_paths": [f"images/{image or name}.png"],
        "expected_evidence_supported": supported,
        "expected_review_required": True,
        "expected_abstention": abstain,
        "source_type": "synthetic",
        "source_reference": "build_boundary.py / boundary-spec-v1",
        "usage_authorization": "项目内原创几何测试图，仅随本仓库用于工程测试；不含第三方照片或素材",
        "annotator": "boundary-spec-v1（自动规格标注，未作真实现场人工复核）",
        "annotation_method": "rule_specification",
        "review_status": "synthetic_spec",
        "coverage_tags": tags,
        "expected_findings": ([{"category": category, "severity": severity}] if hazard else [])
        + ([{"category": "电气线路隐患", "severity": 1}] if "multiple_hazards" in tags else []),
        "evidence_label_note": "未取得独立人工法规标注；False 仅为当前合成证据不足规格，不判断真实违法性",
        "notes": "标签仅针对作者定义的合成规格；不作为真实视觉或法规正确性的验收依据",
    }


if __name__ == "__main__":
    build()
