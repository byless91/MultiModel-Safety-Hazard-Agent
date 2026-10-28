"""Protect real credentials, corpus and databases from regression tests."""

import os
from pathlib import Path

import httpx
import pytest
from app.core.config import get_settings
from app.core.db import engine
from app.main import app
from app.services.providers import get_providers
from fastapi.testclient import TestClient

from _support.environment import ARTIFACTS, ROOT, create_environment, validate_database_url


@pytest.mark.parametrize("url", [
    f"sqlite:///{(ROOT / 'backend/data/app.db').as_posix()}",
    "sqlite:///./data/app.db",
    "sqlite:///file:production.db?uri=true",
    "postgresql+psycopg://user:credential@localhost/safety_hazard",
    "postgresql+psycopg://user:credential@remote/test_safety",
    "not-a-database-url",
])
def test_rejects_unsafe_explicit_database(url):
    with pytest.raises(ValueError, match="TEST_DATABASE_URL") as caught:
        validate_database_url(url)
    assert "credential" not in str(caught.value)


@pytest.mark.parametrize("database", ["safety_test", "test_safety"])
def test_accepts_explicit_local_pg_test_database_without_connecting(database):
    url = f"postgresql+psycopg://test:test@localhost/{database}"
    assert validate_database_url(url) == url


def test_ignores_inherited_database_and_provider_credentials(monkeypatch):
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://production/production")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "must-never-be-used")
    environment = create_environment()
    assert environment.overrides["DATABASE_URL"].startswith("sqlite:///")
    assert environment.overrides["PROVIDER_MODE"] == "mock"
    assert environment.overrides["DASHSCOPE_API_KEY"] == ""
    assert environment.overrides["ZHIPU_API_KEY"] == ""
    # A new run is never pointed at another run's database.
    assert environment.overrides["DATABASE_URL"] != os.environ["DATABASE_URL"]


def test_writes_only_to_the_corpus_copy(monkeypatch):
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    environment = create_environment()
    source = ROOT / "backend/data/knowledge/sample_demo.jsonl"
    original = source.read_bytes()
    copy = Path(environment.overrides["KNOWLEDGE_DIR"]) / source.name
    copy.write_text("test-only replacement", encoding="utf-8")
    assert source.read_bytes() == original


def test_application_singletons_and_health_use_isolated_configuration():
    settings = get_settings()
    assert settings.provider_mode == "mock"
    assert not settings.dashscope_api_key and not settings.zhipu_api_key
    assert all(provider.name == "mock" for provider in get_providers())
    for path in (settings.upload_dir, settings.knowledge_dir, settings.faiss_index_dir,
                 settings.langgraph_checkpoint_path):
        assert path.resolve().is_relative_to(ARTIFACTS.resolve())
    if engine.url.drivername == "sqlite":
        assert Path(engine.url.database).resolve().is_relative_to(ARTIFACTS.resolve())
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200


def test_network_calls_are_blocked_but_fake_transports_work():
    with httpx.Client() as client, pytest.raises(AssertionError, match="Real HTTP"):
        client.get("https://offline-test.invalid")
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
        assert client.get("https://offline-test.invalid").status_code == 200
