"""Add classification mode without rewriting historical assessments or audits."""

import sqlalchemy as sa
from alembic import op

revision = "a12f083bcd71"
down_revision = "f04b62a9c310"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("assessments")}
    if "record_mode" not in columns:
        op.add_column("assessments", sa.Column(
            "record_mode", sa.String(24), nullable=False, server_default="assessment",
        ))
    if "classification_json" not in columns:
        op.add_column("assessments", sa.Column("classification_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("assessments") as batch:
        batch.drop_column("classification_json")
        batch.drop_column("record_mode")
