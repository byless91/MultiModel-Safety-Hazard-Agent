"""R6 schema 2 gate. Never compare historical definitions with new runs."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.eval.gate import compare_reports

BASELINE = ROOT / "docs/evaluation/r6-v2/reports/evaluation_report.json"
POLICY = ROOT / "test/evaluation/gate-policy-v2.json"
CURRENT_DEFAULT = ROOT / "test/.artifacts/evaluation/r6-current/report.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--policy", type=Path, default=POLICY)
    parser.add_argument("--skip-run", action="store_true")
    args = parser.parse_args()
    current_path = args.current or CURRENT_DEFAULT
    if args.current is None and not args.skip_run:
        parent = ROOT / "test/.artifacts/evaluation"
        parent.mkdir(parents=True, exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix="r6-gate-", dir=parent))
        current_path = output / "report.json"
        result = subprocess.run([sys.executable, str(ROOT / "test/evaluation/run_mock.py"),
                                 "--output", str(output)], cwd=ROOT, check=False)
        if result.returncode:
            return 2
    try:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        current = json.loads(current_path.read_text(encoding="utf-8"))
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
        failures = compare_reports(baseline, current, policy)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(f"FAIL report/policy unavailable or invalid: {type(exc).__name__}", file=sys.stderr)
        return 2
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    if failures:
        return 1
    print("PASS schema 2 Mock engineering regression gate (no real-scene quality claim)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
