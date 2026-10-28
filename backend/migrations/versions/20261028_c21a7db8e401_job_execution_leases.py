"""Fence job writes with execution tokens and renewable leases."""

import sqlalchemy as sa
from alembic import op

revision = "c21a7db8e401"
down_revision = "7122c95a212f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("assessment_jobs")}
    for column in (
        sa.Column("worker_id", sa.String(36), nullable=True),
        sa.Column("attempt_token", sa.String(36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    ):
        if column.name not in existing:
            op.add_column("assessment_jobs", column)


def downgrade() -> None:
    with op.batch_alter_table("assessment_jobs") as batch:
        for name in ("lease_expires_at", "attempt_token", "worker_id"):
            batch.drop_column(name)
