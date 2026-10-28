"""Retain the immutable initial request fingerprint for idempotency conflicts."""

import sqlalchemy as sa
from alembic import op

revision = "f04b62a9c310"
down_revision = "e9c31a57db02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("idempotency_keys")}
    if "request_hash" not in columns:
        op.add_column("idempotency_keys", sa.Column("request_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("idempotency_keys") as batch:
        batch.drop_column("request_hash")
