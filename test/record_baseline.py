"""Record R0 from actual report files; do not load application .env or secrets."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _support.baseline import dataset_summary, junit_environment, junit_summary, product_source_digest, vitest_summary

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", type=Path, default=ROOT / "test/.artifacts/reports")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/baselines/r0-2026-10-28.json")
    args = parser.parse_args()
    reports = args.reports_dir
    test_environment = junit_environment(reports / "backend-new.xml")
    if test_environment != junit_environment(reports / "backend-legacy.xml"):
        raise ValueError("Backend reports were produced under different test environments")
    if test_environment != {"database_backend": "sqlite", "provider_mode": "mock"}:
        raise ValueError("This R0 baseline command requires offline SQLite/Mock reports")
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                              capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, check=True,
                           capture_output=True, text=True).stdout != ""
    baseline = {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "git_revision": revision,
        "worktree_dirty": dirty,
        "product_source_sha256": product_source_digest(ROOT),
        "scope": "Local offline SQLite and Mock; no real model or container runtime validation",
        "offline_configuration": {
            "provider_mode": "mock", "auth_mode": "none", "workflow_mode": "sync",
            "real_api_keys": "cleared", "database": "isolated SQLite", "real_http": "blocked",
            "test_artifacts": "test/.artifacts/",
        },
        "backend_new": junit_summary(reports / "backend-new.xml"),
        "backend_legacy": junit_summary(reports / "backend-legacy.xml"),
        "frontend_combined": vitest_summary(reports / "frontend.json"),
        "evaluation_dataset": dataset_summary(ROOT / "backend/data/eval_cases/cases.jsonl"),
        "not_validated": ["PostgreSQL runtime", "Docker runtime", "Real model/image accuracy"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Baseline written: {args.output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
