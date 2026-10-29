"""Add optional location, origin and event time to existing assessments."""

import sqlalchemy as sa
from alembic import op

revision = "d5e2f7a91c04"
down_revision = "b27e619ac430"
branch_labels = None
depends_on = None

COLUMNS = (
    sa.Column("address", sa.Text(), nullable=True),
    sa.Column("district", sa.String(128), nullable=True),
    sa.Column("facility", sa.String(128), nullable=True),
    sa.Column("scene", sa.String(128), nullable=True),
    sa.Column("latitude", sa.Float(), nullable=True),
    sa.Column("longitude", sa.Float(), nullable=True),
    sa.Column("coordinate_source", sa.String(16), nullable=True),
    sa.Column("coordinate_system", sa.String(16), nullable=True),
    sa.Column("data_source", sa.String(24), nullable=True),
    sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
    sa.Column("source_ref", sa.String(128), nullable=True),
    sa.Column("import_batch_id", sa.String(36), nullable=True),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("assessments")}
    for column in COLUMNS:
        if column.name not in columns:
            op.add_column("assessments", column)
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("assessments")}
    if "ix_assessments_data_source" not in indexes:
        op.create_index("ix_assessments_data_source", "assessments", ["data_source"])
    if "ix_assessments_import_batch_id" not in indexes:
        op.create_index("ix_assessments_import_batch_id", "assessments", ["import_batch_id"])
    if "uq_assessments_source_ref" not in indexes:
        op.create_index("uq_assessments_source_ref", "assessments", ["data_source", "source_ref"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_assessments_source_ref", table_name="assessments")
    op.drop_index("ix_assessments_import_batch_id", table_name="assessments")
    op.drop_index("ix_assessments_data_source", table_name="assessments")
    with op.batch_alter_table("assessments") as batch:
        for column in reversed(COLUMNS):
            batch.drop_column(column.name)
