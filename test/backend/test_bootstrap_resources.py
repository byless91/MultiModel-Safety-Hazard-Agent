"""R5/T12: offline seed publishing and packaged operator user initialization."""

import io
import json
import runpy
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from app.cli import create_user
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import verify_password
from app.models import User
from app.services import bootstrap
from app.services.providers.mock import MockProvider
from app.services.rag import RAGService
from sqlalchemy import select


@pytest.fixture
def fresh_settings(tmp_path):
    return get_settings().model_copy(update={
        "knowledge_dir": tmp_path / "knowledge", "faiss_index_dir": tmp_path / "faiss", "provider_mode": "mock",
    })


@pytest.mark.parametrize("empty_directory_exists", [False, True])
def test_fresh_knowledge_is_offline_searchable_and_marked_unreviewed(fresh_settings, empty_directory_exists):
    settings = fresh_settings
    if empty_directory_exists:
        settings.knowledge_dir.mkdir()
    assert bootstrap.bootstrap_knowledge(settings)
    chunks = settings.knowledge_dir / "chunks/real_chunks.jsonl"
    records = [json.loads(line) for line in chunks.read_text(encoding="utf-8").splitlines()]
    assert records
    assert all(record["corpus_scope"] == "development_excerpt" for record in records)
    assert all(record["verification_status"] == "unreviewed" for record in records)
    assert all("未核验" in record["source"] and "开发验证" in record["version"] for record in records)
    rag = RAGService(settings, MockProvider())
    rag.load()
    assert rag.texts and rag.search("楼道堵塞疏散通道", top_k=2)
    assert not list(settings.knowledge_dir.parent.glob(".knowledge-bootstrap-*"))


def test_existing_user_corpus_and_chunks_are_never_replaced(fresh_settings):
    root = fresh_settings.knowledge_dir
    (root / "source_raw").mkdir(parents=True)
    (root / "chunks").mkdir()
    source, chunks = root / "source_raw/uploaded.txt", root / "chunks/real_chunks.jsonl"
    source.write_text("维护人员上传的原语料", encoding="utf-8")
    chunks.write_bytes(b"operator-managed chunks")
    assert not bootstrap.bootstrap_knowledge(fresh_settings)
    assert source.read_text(encoding="utf-8") == "维护人员上传的原语料"
    assert chunks.read_bytes() == b"operator-managed chunks"
    assert len(list((root / "source_raw").iterdir())) == 1


def test_restarts_and_new_seed_versions_preserve_initialized_corpus(fresh_settings, tmp_path):
    assert bootstrap.bootstrap_knowledge(fresh_settings)
    chunks = fresh_settings.knowledge_dir / "chunks/real_chunks.jsonl"
    before = chunks.read_bytes()
    replacement = tmp_path / "new-image-seed"
    shutil.copytree(fresh_settings.knowledge_seed_dir, replacement)
    (replacement / "source_raw/extra.txt").write_text("新版镜像额外内容", encoding="utf-8")
    fresh_settings.knowledge_seed_dir = replacement
    assert not bootstrap.bootstrap_knowledge(fresh_settings)
    assert chunks.read_bytes() == before
    assert not (fresh_settings.knowledge_dir / "source_raw/extra.txt").exists()


def test_failed_chunk_generation_is_not_published_and_can_retry(fresh_settings, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(bootstrap, "write_records", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
        with pytest.raises(OSError, match="disk full"):
            bootstrap.bootstrap_knowledge(fresh_settings)
    assert not fresh_settings.knowledge_dir.exists()
    assert not list(fresh_settings.knowledge_dir.parent.glob(".knowledge-bootstrap-*"))
    assert bootstrap.bootstrap_knowledge(fresh_settings)


@pytest.mark.parametrize("missing", [True, False])
def test_missing_or_empty_seed_fails_without_publishing(fresh_settings, tmp_path, missing):
    fresh_settings.knowledge_seed_dir = tmp_path / "broken-seed"
    if not missing:
        (fresh_settings.knowledge_seed_dir / "source_raw").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="种子"):
        bootstrap.bootstrap_knowledge(fresh_settings)
    assert not fresh_settings.knowledge_dir.exists()


def test_operator_write_during_initialization_wins(fresh_settings, monkeypatch):
    original = bootstrap.collect_directory_records

    def collect(path):
        records = original(path)
        fresh_settings.knowledge_dir.mkdir()
        (fresh_settings.knowledge_dir / "operator.txt").write_text("用户写入", encoding="utf-8")
        return records

    monkeypatch.setattr(bootstrap, "collect_directory_records", collect)
    assert not bootstrap.bootstrap_knowledge(fresh_settings)
    assert [path.name for path in fresh_settings.knowledge_dir.iterdir()] == ["operator.txt"]


def test_packaged_cli_creates_login_user_without_http_auth_and_bootstrap_preserves_it(
    review_client, fresh_settings, monkeypatch, capsys,
):
    username, password = f"admin-{uuid4().hex[:10]}", "offline-admin-pass"
    monkeypatch.setattr(create_user.sys, "stdin", io.StringIO(password + "\n"))
    assert create_user.main(["--username", username, "--role", "admin", "--password-stdin"]) == 0
    assert password not in capsys.readouterr().out
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        old_hash = user.password_hash
        assert old_hash != password and verify_password(password, old_hash)
    bootstrap.bootstrap_knowledge(fresh_settings)
    bootstrap.bootstrap_knowledge(fresh_settings)
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.username == username)).password_hash == old_hash
    monkeypatch.setattr(get_settings(), "auth_mode", "jwt")
    response = review_client.post("/api/v1/auth/token", data={"username": username, "password": password})
    assert response.status_code == 200
    token = response.json()["access_token"]
    assert review_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["role"] == "admin"


def test_cli_invalid_password_writes_no_user(review_client, capsys):
    username = f"short-{uuid4().hex[:8]}"
    assert create_user.main(["--username", username, "--password", "short"]) == 1
    assert "至少 8 位" in capsys.readouterr().err
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.username == username)) is None


def test_old_script_remains_a_thin_compatibility_entrypoint():
    root = Path(__file__).resolve().parents[2]
    namespace = runpy.run_path(str(root / "scripts/create_user.py"))
    assert namespace["main"] is create_user.main
