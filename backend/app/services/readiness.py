"""Bound readiness to persistent dependencies; never treat liveness as readiness."""

import json
import tempfile
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.config import BACKEND_DIR, get_settings
from app.core.db import SessionLocal
from app.services.job_runner import get_job_runner
from app.services.rag import get_rag


@lru_cache
def expected_heads() -> set[str]:
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return set(ScriptDirectory.from_config(config).get_heads())


def storage_writable(paths: list[Path]) -> bool:
    try:
        for path in set(paths):
            with tempfile.TemporaryFile(dir=path) as probe:
                probe.write(b"ready")
                probe.flush()
        return True
    except OSError:
        return False


def readiness_report() -> dict:
    settings = get_settings()
    checks = {"database": False, "schema": False, "knowledge": False, "storage": False, "worker": False}
    try:
        with SessionLocal() as db:
            checks["database"] = db.scalar(text("SELECT 1")) == 1
            versions = set(db.scalars(text("SELECT version_num FROM alembic_version")))
            checks["schema"] = versions == expected_heads()
    except Exception:
        pass  # Public readiness contains booleans, never database addresses or credentials.
    chunks = 0
    scope = "operator_managed_unverified"
    try:
        rag = get_rag()
        snapshot = rag.readiness_snapshot()
        chunks = snapshot["chunks"]
        persisted = [*settings.knowledge_dir.glob("*.jsonl"), *settings.knowledge_dir.glob("chunks/*.jsonl")]
        checks["knowledge"] = (chunks > 0 and snapshot["index_ready"]
                               and any(path.is_file() and path.stat().st_size > 0 for path in persisted))
        marker = settings.knowledge_dir / ".bootstrap.json"
        if marker.exists():
            metadata = json.loads(marker.read_text(encoding="utf-8"))
            scope = "development_seed_unreviewed" if metadata.get("verification_status") == "unreviewed" else "unknown"
    except Exception:
        checks["knowledge"] = False
    checks["storage"] = storage_writable([
        settings.upload_dir, settings.knowledge_dir, settings.faiss_index_dir,
        settings.langgraph_checkpoint_path.parent,
    ])
    checks["worker"] = settings.workflow_mode == "sync" or get_job_runner().healthy
    return {"status": "ready" if all(checks.values()) else "not_ready", "checks": checks,
            "knowledge_chunks": chunks, "knowledge_scope": scope, "version": settings.app_version}
