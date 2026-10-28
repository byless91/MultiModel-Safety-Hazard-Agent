"""Early bootstrap also usable with the unmodified legacy pytest suite."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy.engine import make_url

from _support.environment import ARTIFACTS, create_environment

ENVIRONMENT = create_environment()
ENVIRONMENT.activate()

# Cache settings before legacy conftest overrides environment variables.
# The application has import-time settings/engine/provider singletons.
from app.core.config import get_settings  # noqa: E402

get_settings()


def pytest_configure(config: pytest.Config) -> None:
    ENVIRONMENT.activate()
    basetemp = Path(config.option.basetemp).resolve() if config.option.basetemp else ENVIRONMENT.directory / "tmp"
    if not basetemp.is_relative_to(ARTIFACTS.resolve()) or basetemp == ARTIFACTS.resolve():
        raise pytest.UsageError("--basetemp must be a subdirectory of test/.artifacts")
    config.option.basetemp = str(basetemp)
    # A fresh checkout has source_raw but no generated chunks.
    from app.services.knowledge import collect_directory_records, write_records

    knowledge = Path(ENVIRONMENT.overrides["KNOWLEDGE_DIR"])
    if not (knowledge / "chunks" / "real_chunks.jsonl").exists():
        write_records(collect_directory_records(knowledge / "source_raw"), knowledge / "chunks")


@pytest.fixture(scope="session", autouse=True)
def record_offline_environment(record_testsuite_property) -> None:
    record_testsuite_property("database_backend", make_url(ENVIRONMENT.overrides["DATABASE_URL"]).get_backend_name())
    record_testsuite_property("provider_mode", "mock")


@pytest.fixture(autouse=True)
def block_real_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """MockTransport and TestClient remain usable; paid HTTP calls fail closed."""
    def denied(*args, **kwargs):
        raise AssertionError("Real HTTP is disabled in offline tests; use httpx.MockTransport")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", denied)
