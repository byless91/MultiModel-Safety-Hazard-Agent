"""M6 knowledge-pack import results and local sync status."""

from datetime import datetime

from pydantic import BaseModel, Field


class PackFailure(BaseModel):
    index: int
    title: str
    reason: str


class PackImportResultOut(BaseModel):
    pack_version: str
    manifest_sha256: str
    imported: int
    skipped: int
    superseded: int
    failed: int
    failures: list[PackFailure] = Field(default_factory=list)
    indexed: bool = False
    index_error: str | None = None


class PackSyncOut(BaseModel):
    pack_version: str
    manifest_sha256: str
    imported: int
    skipped: int
    superseded: int
    failed: int
    imported_by: str | None = None
    imported_at: datetime


class PackStatusOut(BaseModel):
    last_sync: PackSyncOut | None = None
