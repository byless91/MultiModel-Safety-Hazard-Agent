"""Identify a reserved followup independently of an execution attempt."""

import sqlalchemy as sa
from alembic import op

revision = "e9c31a57db02"
down_revision = "c21a7db8e401"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("assessments")}
    if "followup_token" not in columns:
        op.add_column("assessments", sa.Column("followup_token", sa.String(36), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("assessments") as batch:
        batch.drop_column("followup_token")
