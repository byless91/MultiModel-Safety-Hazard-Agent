"""评测回归门禁（B6/WP5.3）：当前评测与基线对比，关键指标劣化超阈值即失败。

用法：
  python scripts/check_eval_baseline.py                       # 当前跑一轮 mock 评测再对比
  python scripts/check_eval_baseline.py --current a.json      # 直接用已有报告对比

阈值（可调）：类别准确率、人工复核率（高风险复核率代理）下降 > 2pp 失败；
不安全自动通过率上升 > 2pp 失败。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs" / "evaluation" / "reports" / "evaluation_report.json"
CURRENT_DEFAULT = ROOT / "backend" / "data" / "eval" / "report.json"

# 指标方向：True = 越高越好；False = 越低越好
GATED_METRICS = {
    "category_accuracy": True,
    "human_review_rate": True,  # 高风险复核率代理：复核率不应无故下降
    "unsafe_auto_pass_rate": False,  # 安全底线：不安全自动通过率不应上升
}
TOLERANCE = 0.02  # 2pp


def _load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and not data.get("metrics"):
        # 兼容两种报告结构：扁平或嵌套 metrics
        return data
    return data.get("metrics") or {}


def main() -> int:
    parser = argparse.ArgumentParser(description="评测回归门禁")
    parser.add_argument("--current", type=Path, default=None, help="当前评测报告路径")
    parser.add_argument("--baseline", type=Path, default=BASELINE, help="基线报告路径")
    parser.add_argument("--skip-run", action="store_true", help="不重跑评测，直接用 --current")
    args = parser.parse_args()

    if not args.baseline.exists():
        print(f"FAIL 基线文件不存在：{args.baseline}", file=sys.stderr)
        return 2

    if args.current is None and not args.skip_run:
        print("运行 mock 模式评测（60 条）...")
        result = subprocess.run(
            [
                sys.executable,  # CI 里经 uv run 调用即为 venv 解释器
                str(ROOT / "scripts" / "evaluate.py"),
                "--provider",
                "mock",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print("FAIL 评测执行失败", file=sys.stderr)
            print(result.stdout[-2000:], file=sys.stderr)
            return 2

    current_path = args.current or CURRENT_DEFAULT
    if not current_path.exists():
        print(f"FAIL 当前报告不存在：{current_path}", file=sys.stderr)
        return 2

    baseline = _load(args.baseline)
    current = _load(current_path)

    failures: list[str] = []
    print(f"{'指标':<28}{'基线':>10}{'当前':>10}{'判定':>8}")
    print("-" * 60)
    for metric, higher_is_better in GATED_METRICS.items():
        base_value = float(baseline.get(metric, 0) or 0)
        curr_value = float(current.get(metric, 0) or 0)
        if higher_is_better:
            ok = curr_value >= base_value - TOLERANCE
            delta = curr_value - base_value
        else:
            ok = curr_value <= base_value + TOLERANCE
            delta = base_value - curr_value
        verdict = "PASS" if ok else "FAIL"
        print(f"{metric:<28}{base_value:>10.4f}{curr_value:>10.4f}{verdict:>8}")
        if not ok:
            failures.append(
                f"{metric}: 基线 {base_value:.4f} -> 当前 {curr_value:.4f}"
                f"（允许劣化 {TOLERANCE * 100:.0f}pp）"
            )

    if failures:
        print("\n评测回归门禁未通过：", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print("\n评测回归门禁通过：关键指标未劣化。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
