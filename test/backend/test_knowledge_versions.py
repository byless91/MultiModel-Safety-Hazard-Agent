"""M2: version identity, human publication and immutable citations."""

from uuid import uuid4

import pytest
from app.core.db import SessionLocal
from app.models import KnowledgeDocument
from app.schemas.knowledge import KnowledgeMetadataIn, KnowledgeReviewIn
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError


def test_approval_requires_explicit_source_check_and_nonblank_note():
    for payload in ({"source_checked": False, "note": "核对了"}, {"source_checked": True, "note": "  "}):
        with pytest.raises(ValidationError):
            KnowledgeReviewIn(decision="approve", revision=0, **payload)


def test_unknown_industry_is_not_silently_classified():
    with pytest.raises(ValidationError):
        KnowledgeMetadataIn(title="文档", industry="unknown-industry")


@pytest.mark.parametrize("duplicate", ["version", "active"])
def test_database_prevents_duplicate_versions_and_two_active_versions(review_client, duplicate):
    series = str(uuid4())
    with SessionLocal() as db:
        db.add_all([
            KnowledgeDocument(title="版本一", series_id=series, version="v1", review_status="approved"),
            KnowledgeDocument(title="版本二", series_id=series, version="v1" if duplicate == "version" else "v2",
                              review_status="unreviewed" if duplicate == "version" else "approved"),
        ])
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
