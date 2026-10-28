"""Create an offline test environment before importing application singletons."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "test" / ".artifacts"


def validate_database_url(value: str) -> str:
    """Accept only local artifact files or an explicitly named local PG test DB.

    Never include a rejected URL in errors: it may contain credentials.
    """
    try:
        url = make_url(value)
        if url.drivername == "sqlite":
            if not url.database or url.query or url.database == ":memory:":
                raise ValueError
            target = Path(url.database)
            if not target.is_absolute() or not target.resolve().is_relative_to(ARTIFACTS.resolve()):
                raise ValueError
            return value
        if url.drivername == "postgresql+psycopg":
            database = url.database or ""
            if url.host not in {"localhost", "127.0.0.1", "::1"} or url.query:
                raise ValueError
            if not (database.startswith("test_") or database.endswith("_test")):
                raise ValueError
            return value
    except (ArgumentError, ValueError, TypeError):
        pass
    raise ValueError(
        "TEST_DATABASE_URL must name an artifact SQLite file or a local PostgreSQL test database"
    ) from None


@dataclass(frozen=True)
class TestEnvironment:
    directory: Path
    overrides: dict[str, str]

    def activate(self) -> None:
        os.environ.update(self.overrides)
        # tempfile may already have cached the user's system temp directory.
        tempfile.tempdir = self.overrides["TMPDIR"]


def create_environment() -> TestEnvironment:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="backend-", dir=ARTIFACTS)).resolve()
    requested = os.environ.get("TEST_DATABASE_URL")
    database_url = validate_database_url(requested or f"sqlite:///{(directory / 'test.db').as_posix()}")
    knowledge = directory / "knowledge"
    shutil.copytree(ROOT / "backend" / "data" / "knowledge", knowledge)
    for name in ("uploads", "faiss", "temp"):
        (directory / name).mkdir()
    overrides = {
        "DATABASE_URL": database_url,
        "PROVIDER_MODE": "mock",
        "DASHSCOPE_API_KEY": "",
        "ZHIPU_API_KEY": "",
        "API_BEARER_TOKEN": "",
        "AUTH_MODE": "none",
        "AUTH_JWT_SECRET": "offline-test-secret-at-least-32-bytes",
        "WORKFLOW_MODE": "sync",
        "RATE_LIMIT_ENABLED": "false",
        "DAILY_TOKEN_BUDGET": "0",
        "MOCK_DEMO_BOOST": "false",
        "MAX_FOLLOWUPS": "2",
        "UPLOAD_DIR": str(directory / "uploads"),
        "KNOWLEDGE_DIR": str(knowledge),
        "FAISS_INDEX_DIR": str(directory / "faiss"),
        "LANGGRAPH_CHECKPOINT_PATH": str(directory / "checkpoint.db"),
        "TMPDIR": str(directory / "temp"),
        "TMP": str(directory / "temp"),
        "TEMP": str(directory / "temp"),
    }
    return TestEnvironment(directory, overrides)
