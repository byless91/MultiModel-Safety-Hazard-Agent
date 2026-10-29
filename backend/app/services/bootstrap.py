"""Publish development knowledge seeds only to a new, empty knowledge directory."""

import json
import logging
import shutil
import tempfile
import time
from pathlib import Path

from app.core.config import Settings
from app.services.knowledge import collect_directory_records, write_records

logger = logging.getLogger("safety_hazard.bootstrap")


def bootstrap_knowledge(settings: Settings) -> bool:
    """Build chunks offline, then publish together. Never refresh an existing corpus."""
    target = settings.knowledge_dir
    if target.exists() and any(target.iterdir()):
        return False
    seed = settings.knowledge_seed_dir
    if not (seed / "source_raw").is_dir():
        raise RuntimeError("初始知识种子缺失，请检查后端资源打包或 KNOWLEDGE_SEED_DIR")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".knowledge-bootstrap-", dir=target.parent) as scratch:
        staged = Path(scratch) / "knowledge"
        shutil.copytree(seed, staged)
        records = collect_directory_records(staged / "source_raw")
        if not records:
            raise RuntimeError("初始知识种子未生成有效切片，拒绝发布空知识库")
        for record in records:
            record["corpus_scope"] = "development_excerpt"
            record["verification_status"] = "unreviewed"
            record["source"] = f"[开发节选，未核验现行有效性] {record['source']}"
            record["version"] = f"开发验证 / {record['version']}"
        write_records(records, staged / "chunks")
        (staged / ".bootstrap.json").write_text(json.dumps({
            "seed_version": 1, "corpus_scope": "development_excerpt",
            "verification_status": "unreviewed", "chunks": len(records),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Another initializer or operator may have populated the target during chunking.
        if target.exists():
            if any(target.iterdir()):
                return False
            target.rmdir()  # Empty target only; never recursively remove user knowledge.
        for attempt in range(5):
            try:
                staged.rename(target)
                break
            except OSError as exc:
                if target.is_dir() and any(target.iterdir()):
                    return False
                # Windows may briefly retain a deleted empty directory handle.
                # Retry only the atomic rename, never copy over user data or change ACLs.
                if isinstance(exc, PermissionError) and getattr(exc, "winerror", None) in {5, 32} and attempt < 4:
                    time.sleep(0.05 * (attempt + 1))
                    continue
                raise
    logger.warning("已离线初始化开发法规节选 %d 片；正式使用前须人工核验来源、版本和适用性", len(records))
    return True
