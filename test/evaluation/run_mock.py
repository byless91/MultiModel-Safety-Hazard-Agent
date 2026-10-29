"""Reproducible Mock CLI batches with a fresh, offline knowledge copy."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "test")]

from _support.environment import ARTIFACTS, create_environment  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ARTIFACTS / "evaluation/r6-current")
    parser.add_argument("--ablation", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ARTIFACTS.resolve()):
        parser.error("Mock outputs must be inside test/.artifacts")
    environment = create_environment()
    environment.overrides["KNOWLEDGE_DIR"] = str(environment.directory / "evaluation-knowledge")
    environment.activate()
    from app.core.config import Settings
    from app.services.bootstrap import bootstrap_knowledge

    bootstrap_knowledge(Settings(_env_file=None))
    script = "ablation.py" if args.ablation else "evaluate.py"
    command = [
        sys.executable,
        str(ROOT / "scripts" / script),
        "--provider",
        "mock",
        "--cases",
        str(ROOT / "test/evaluation/cases.jsonl"),
        "--output",
        str(output),
        "--gate-policy",
        str(ROOT / "test/evaluation/gate-policy-v2.json"),
    ]
    return subprocess.run(command, cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
