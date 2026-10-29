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


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if item.nodeid == "tests/test_eval_robustness.py::test_safe_ground_truth_is_not_silently_auto_passed":
            item.add_marker(pytest.mark.xfail(
                strict=True,
                raises=AssertionError,
                reason="R6/T16 counts false findings as FP even after review; replacement: "
                       "test/backend/test_eval_detection_metrics.py::test_original_safe_mock_case_exposes_false_alarm",
            ))
        if item.nodeid == "tests/test_workflow_jobs.py::test_async_second_followup_falls_back_to_full_rerun":
            item.add_marker(pytest.mark.xfail(
                strict=True,
                raises=AssertionError,
                reason="R1/T03 intentionally rejects followup after completion (409); replacement: "
                       "test/backend/test_review_state_guards.py",
            ))


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
