# -*- coding: utf-8 -*-
"""Generate the formal evaluation documentation under docs/evaluation.

Source of truth is ``backend/data/eval/`` (runner outputs). This script only
copies/links artifacts and renders the human-readable README; it never invents
metrics or switches a Mock report into a real-model report.
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
EVAL_DIR = BACKEND / "data" / "eval"
DOCS_DIR = ROOT / "docs" / "evaluation"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_readme(
    *,
    dataset_version: str,
    case_count: int,
    provider_mode: str,
    variants: dict,
    partitions: dict,
    evaluation_payload: dict | None = None,
    generated_at: str,
) -> str:
    lines = [
        "# 评测体系文档",
        "",
        "本目录是正式评测体系的说明和结果归档。评测本身由 `scripts/evaluate.py` 与",
        "`scripts/ablation.py` 执行，数据源为 `backend/data/eval_cases/`。",
        "",
        "## 评测命令",
        "",
        "```powershell",
        ".\\backend\\.venv\\Scripts\\python.exe scripts\\evaluate.py --provider mock --variant full",
        ".\\backend\\.venv\\Scripts\\python.exe scripts\\ablation.py --provider mock",
        "```",
        "",
        "真实模型评测（按量计费）：把上面 `--provider mock` 换成 `--provider auto`。",
        "",
        "## 当前归档",
        "",
        f"- 数据集版本：`{dataset_version}`, 案例数：`{case_count}`",
        f"- 数据来源分布：`{json.dumps(partitions, ensure_ascii=False)}`",
        f"- 执行模式：`{provider_mode}`（`mock`=确定性 Mock，`auto`=真实模型）",
        f"- 归档时间：`{generated_at}`",
        "",
        "- 数据集：`dataset/`",
        "- A-F 对比报告：`reports/ablation_report.md`",
        "- 清洗后的逐条结果：`results/ablation_results.jsonl`",
        "- 单变体正式报告：`reports/evaluation_report.md`（如果存在）",
        "",
        "## 消融对比表",
        "",
    ]
    lines.append("| 变体 | 数据模式 | 类别 | 等级 | MAE | 条款 | 证据支持 | 复核 | 分歧 | Unsafe |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for name, item in sorted(variants.items()):
        metrics = item.get("metrics") or {}
        lines.append(
            f"| {item.get('label', name)} | {item.get('mode', provider_mode)} "
            f"| {metrics.get('category_accuracy', '-')} "
            f"| {metrics.get('level_accuracy', '-')} "
            f"| {metrics.get('severity_mae', '-')} "
            f"| {metrics.get('clause_hit_rate', '-')} "
            f"| {metrics.get('evidence_support_rate', '-')} "
            f"| {metrics.get('human_review_rate', '-')} "
            f"| {metrics.get('model_conflict_rate', '-')} "
            f"| {metrics.get('unsafe_auto_pass_rate', '-')} |"
        )
    lines.extend(
        [
            "## 来源与模式说明",
            "",
            "- `curated / official / donated`：人工整理的**真实标注数据**。",
            "- `synthetic`：合成/边界案例，报告中按 `source_type` 单独统计，不混入真实标注结果。",
            "- `mock`：未配置 API Key 或显式 `--provider mock` 时的确定性 Mock 输出，",
            "  报告中必须标注 `evaluation_mode=mock`，禁止冒充真实评测。",
        ]
    )
    if evaluation_payload:
        overview = evaluation_payload.get("dataset_overview") or {}
        if overview:
            lines.extend(
                [
                    "",
                    "## Dataset Overview",
                    "",
                    f"- 类别分布：`{json.dumps(overview.get('category_counts', {}), ensure_ascii=False)}`",
                    f"- 等级分布：`{json.dumps(overview.get('severity_counts', {}), ensure_ascii=False)}`",
                    f"- 有隐患样本：`{overview.get('hazard_case_count')}`；"
                    f"无隐患负样本：`{overview.get('safe_negative_case_count')}`；"
                    f"含图片：`{overview.get('image_case_count')}`",
                ]
            )
        limitations = evaluation_payload.get("limitations")
        lines.extend(["", "## Limitations", ""])
        shown = list(limitations or [])
        overview_notes = (evaluation_payload.get("dataset_overview") or {}).get(
            "limitation_notes"
        ) or []
        for note in overview_notes:
            if note not in shown:
                shown.append(note)
        if not shown:
            shown.append("尚未进行真实模型完整回归与多场景图片评测")
        for note in shown:
            lines.append(f"- {note}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 docs/evaluation 文档")
    parser.add_argument(
        "--eval-dir",
        type=Path,
        default=EVAL_DIR,
        help="评测输出目录（默认 backend/data/eval）",
    )
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=DOCS_DIR,
        help="文档输出目录（默认 docs/evaluation）",
    )
    args = parser.parse_args()

    eval_dir = args.eval_dir
    docs_dir = args.docs_dir
    report_path = eval_dir / "ablation_report.json"
    if not report_path.exists():
        print(f"缺少 {report_path}，请先运行 scripts/ablation.py")
        sys.exit(1)
    report = _read_json(report_path)
    cases_path = eval_dir.parent / "eval_cases" / "cases.jsonl"

    (docs_dir / "dataset").mkdir(parents=True, exist_ok=True)
    (docs_dir / "reports").mkdir(parents=True, exist_ok=True)
    (docs_dir / "results").mkdir(parents=True, exist_ok=True)
    if cases_path.exists():
        shutil.copy2(cases_path, docs_dir / "dataset" / f"cases_{report.get('dataset_version', 'v1')}.jsonl")
    dataset_meta = eval_dir.parent / "eval_cases" / "dataset_meta.json"
    if dataset_meta.exists():
        shutil.copy2(dataset_meta, docs_dir / "dataset" / "dataset_meta.json")
    shutil.copy2(eval_dir / "ablation_report.md", docs_dir / "reports" / "ablation_report.md")
    shutil.copy2(eval_dir / "ablation_report.json", docs_dir / "reports" / "ablation_report.json")
    if (eval_dir / "ablation_results.jsonl").exists():
        shutil.copy2(
            eval_dir / "ablation_results.jsonl",
            docs_dir / "results" / "ablation_results.jsonl",
        )
    if (eval_dir / "report.md").exists() and (eval_dir / "report.json").exists():
        shutil.copy2(eval_dir / "report.md", docs_dir / "reports" / "evaluation_report.md")
        shutil.copy2(eval_dir / "report.json", docs_dir / "reports" / "evaluation_report.json")
        shutil.copy2(eval_dir / "results.jsonl", docs_dir / "results" / "evaluation_results.jsonl")

    readme = build_readme(
        dataset_version=report.get("dataset_version", "v1"),
        case_count=report.get("case_count", 0),
        provider_mode=report.get("provider_mode", "mock"),
        variants=report.get("variants", {}),
        partitions=report.get("partitions", report.get("source_type_counts", {})),
        evaluation_payload=(
            _read_json(eval_dir / "report.json")
            if (eval_dir / "report.json").exists()
            else None
        ),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    (docs_dir / "README.md").write_text(readme, encoding="utf-8")
    print(f"docs/evaluation 已生成：{docs_dir}")
    print(f"  - README.md（含 A-F 对比）")
    print(f"  - reports/ablation_report.md / evaluation_report.md")
    print(f"  - results/ 逐条结果、dataset/ 数据集副本")


if __name__ == "__main__":
    main()
