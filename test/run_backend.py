"""Run new and legacy suites in separate, offline application processes."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("new", "legacy", "all"), default="all")
    parser.add_argument("--reports-dir", type=Path, default=ROOT / "test/.artifacts/reports")
    args, pytest_args = parser.parse_known_args()
    reports = args.reports_dir.resolve()
    if not reports.is_relative_to((ROOT / "test/.artifacts").resolve()):
        parser.error("--reports-dir must be inside test/.artifacts")
    reports.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join((str(ROOT / "backend"), str(ROOT / "test")))
    suites = ("new", "legacy") if args.suite == "all" else (args.suite,)
    failed = False
    for suite in suites:
        print(f"Running {suite} backend suite in an isolated process", flush=True)
        cwd = ROOT if suite == "new" else ROOT / "backend"
        target = "test/backend" if suite == "new" else "tests"
        report_args = [] if {"--collect-only", "--co"} & set(pytest_args) else [
            f"--junitxml={reports / f'backend-{suite}.xml'}",
        ]
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "_support.pytest_isolation", "-p", "no:cacheprovider",
             target, *report_args, *pytest_args],
            cwd=cwd,
            env=environment,
            check=False,
        )
        failed = failed or result.returncode != 0
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
