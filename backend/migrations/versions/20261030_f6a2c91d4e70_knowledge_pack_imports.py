"""Add knowledge-pack import history and the local sync marker."""

import sqlalchemy as sa
from alembic import op

revision = "f6a2c91d4e70"
down_revision = "e91c4f7a2d68"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "knowledge_pack_imports" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "knowledge_pack_imports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("pack_version", sa.String(32), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("superseded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_by", sa.String(64), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("knowledge_pack_imports")
