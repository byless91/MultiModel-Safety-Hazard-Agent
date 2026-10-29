"""Version and review existing knowledge documents without promoting legacy content."""

import sqlalchemy as sa
from alembic import op

revision = "b27e619ac430"
down_revision = "a12f083bcd71"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("knowledge_documents")}
    additions = [
        sa.Column("industry", sa.String(24), nullable=False, server_default="general"),
        sa.Column("applicability", sa.Text(), nullable=False, server_default=""),
        sa.Column("review_status", sa.String(24), nullable=False, server_default="unreviewed"),
        sa.Column("series_id", sa.String(36), nullable=True),
        sa.Column("supersedes_id", sa.String(36), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("review_json", sa.Text(), nullable=True),
    ]
    for column in additions:
        if column.name not in columns:
            op.add_column("knowledge_documents", column)
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("knowledge_documents")}
    if "uq_knowledge_series_version" not in indexes:
        op.create_index("uq_knowledge_series_version", "knowledge_documents", ["series_id", "version"], unique=True)
    if "uq_knowledge_active_series" not in indexes:
        op.create_index("uq_knowledge_active_series", "knowledge_documents", ["series_id"], unique=True,
                        sqlite_where=sa.text("review_status = 'approved'"),
                        postgresql_where=sa.text("review_status = 'approved'"))


def downgrade() -> None:
    op.drop_index("uq_knowledge_active_series", table_name="knowledge_documents")
    op.drop_index("uq_knowledge_series_version", table_name="knowledge_documents")
    with op.batch_alter_table("knowledge_documents") as batch:
        for name in ("review_json", "content_sha256", "supersedes_id", "series_id",
                     "review_status", "applicability", "industry"):
            batch.drop_column(name)
