"""Start a disposable Mock backend for local browser recovery verification."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "test"), str(ROOT / "backend")]

from _support.environment import ARTIFACTS, create_environment  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    args = parser.parse_args()
    state_file = args.state_file.resolve()
    if not state_file.is_relative_to(ARTIFACTS.resolve()):
        parser.error("state file must remain under test/.artifacts")
    # Never accept a caller's real or shared test database for this browser run.
    os.environ.pop("TEST_DATABASE_URL", None)
    environment = create_environment()
    environment.activate()
    os.environ["WORKFLOW_MODE"] = "async"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"database_url": environment.overrides["DATABASE_URL"]}), encoding="utf-8")
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
