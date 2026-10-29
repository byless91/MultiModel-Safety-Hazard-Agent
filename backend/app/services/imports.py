"""Deduplicated, traceable record import with a per-row failure list."""

from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Assessment
from app.schemas.location import ImportRow

MAX_REASON_LENGTH = 300


def import_reason(error: ValidationError) -> str:
    parts = []
    for item in error.errors():
        field = ".".join(str(part) for part in item["loc"]) or "行"
        parts.append(f"{field}: {item['msg']}")
    return "；".join(parts)[:MAX_REASON_LENGTH]


def import_rows(db: Session, rows: list[object]) -> dict:
    """Insert valid rows in one batch; invalid or duplicate rows never block the rest."""
    batch_id = str(uuid4())
    failures: list[dict] = []
    duplicates: list[int] = []
    valid: list[tuple[int, ImportRow]] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(rows, start=1):
        try:
            row = ImportRow.model_validate(raw)
        except ValidationError as exc:
            source_ref = raw.get("source_ref") if isinstance(raw, dict) else None
            failures.append({"row": index, "source_ref": source_ref if isinstance(source_ref, str) else None,
                             "reason": import_reason(exc)})
            continue
        key = (row.data_source, row.source_ref)
        if key in seen:
            duplicates.append(index)
            continue
        seen.add(key)
        valid.append((index, row))
    existing = set()
    if valid:
        existing = {
            (source, ref) for source, ref in db.execute(
                select(Assessment.data_source, Assessment.source_ref)
                .where(Assessment.source_ref.in_([row.source_ref for _, row in valid]))
            ).all()
        }
    imported = 0
    for index, row in valid:
        if (row.data_source, row.source_ref) in existing:
            duplicates.append(index)
            continue
        db.add(Assessment(
            id=str(uuid4()), description=row.description, status="imported", record_mode="imported",
            address=row.address or None, district=row.district or None, facility=row.facility or None,
            scene=row.scene or None, latitude=row.latitude, longitude=row.longitude,
            coordinate_source="import" if row.latitude is not None else None,
            coordinate_system=row.coordinate_system, data_source=row.data_source,
            event_time=row.event_time, source_ref=row.source_ref, import_batch_id=batch_id,
        ))
        imported += 1
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="导入与现有记录冲突，请检查外部编号后重试") from exc
    return {"batch_id": batch_id, "imported": imported, "duplicates": sorted(duplicates),
            "failures": failures}
