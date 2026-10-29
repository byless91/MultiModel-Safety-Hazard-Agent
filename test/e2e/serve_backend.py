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
    parser.add_argument("--auth-mode", choices=["none", "token", "jwt"], default="none")
    parser.add_argument("--workflow-gate", type=Path, help="Test-only pause file under test/.artifacts")
    args = parser.parse_args()
    state_file = args.state_file.resolve()
    if not state_file.is_relative_to(ARTIFACTS.resolve()):
        parser.error("state file must remain under test/.artifacts")
    if args.workflow_gate and not args.workflow_gate.resolve().is_relative_to(ARTIFACTS.resolve()):
        parser.error("workflow gate must remain under test/.artifacts")
    # Never accept a caller's real or shared test database for this browser run.
    os.environ.pop("TEST_DATABASE_URL", None)
    environment = create_environment()
    # A clean checkout has no generated chunks. Use only packaged development
    # seeds, initialized by lifespan, rather than a developer's uploaded corpus.
    environment.overrides["KNOWLEDGE_DIR"] = str(environment.directory / "browser-knowledge")
    environment.activate()
    os.environ["WORKFLOW_MODE"] = "async"
    os.environ["AUTH_MODE"] = args.auth_mode
    os.environ["AUTH_JWT_SECRET"] = "r5-browser-signing-secret-at-least-32-bytes"
    os.environ["API_BEARER_TOKEN"] = "r5-browser-static-credential" if args.auth_mode == "token" else ""
    if args.auth_mode == "jwt":
        from app.cli.create_user import main as create_user

        create_user(["--username", "browser-admin", "--role", "admin", "--password", "browser-pass-123"])
    if args.workflow_gate:
        import time

        from app.services import workflow

        original = workflow.run_workflow

        def controlled_workflow(*values, **kwargs):
            while args.workflow_gate.exists():
                time.sleep(0.05)
            if "R7_TEST_JOB_FAILURE" in kwargs.get("description", ""):
                raise RuntimeError("R7_TEST_ONLY: model failure")
            return original(*values, **kwargs)

        workflow.run_workflow = controlled_workflow
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"database_url": environment.overrides["DATABASE_URL"],
                                      "knowledge_dir": environment.overrides["KNOWLEDGE_DIR"]}), encoding="utf-8")
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
