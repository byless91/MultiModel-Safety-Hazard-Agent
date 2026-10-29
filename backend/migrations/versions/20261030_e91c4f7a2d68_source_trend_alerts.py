"""Add authoritative source reminders and explainable trend alerts."""

import sqlalchemy as sa
from alembic import op

revision = "e91c4f7a2d68"
down_revision = "d5e2f7a91c04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "knowledge_sources" not in tables:
        op.create_table(
            "knowledge_sources",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("industry", sa.String(24), nullable=False, server_default="general"),
            sa.Column("last_hash", sa.String(64), nullable=True),
            sa.Column("acknowledged_hash", sa.String(64), nullable=True),
            sa.Column("last_status", sa.String(24), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("change_detected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "trend_alerts" not in tables:
        op.create_table(
            "trend_alerts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("rule_version", sa.String(32), nullable=False),
            sa.Column("scope_type", sa.String(24), nullable=False, server_default="category"),
            sa.Column("scope_value", sa.String(128), nullable=False),
            sa.Column("month", sa.String(7), nullable=False),
            sa.Column("observed", sa.Integer(), nullable=False),
            sa.Column("baseline", sa.Float(), nullable=False),
            sa.Column("ratio_threshold", sa.Float(), nullable=False),
            sa.Column("sample_size", sa.Integer(), nullable=False),
            sa.Column("explanation", sa.Text(), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="open"),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("reviewed_by_name", sa.String(64), nullable=True),
            sa.Column("reviewed_by_id", sa.String(36), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("trend_alerts")}
    if "ix_trend_alerts_scope_value" not in indexes:
        op.create_index("ix_trend_alerts_scope_value", "trend_alerts", ["scope_value"])
    if "ix_trend_alerts_month" not in indexes:
        op.create_index("ix_trend_alerts_month", "trend_alerts", ["month"])
    if "uq_trend_alert_scope_month" not in indexes:
        op.create_index(
            "uq_trend_alert_scope_month", "trend_alerts",
            ["rule_version", "scope_type", "scope_value", "month"], unique=True,
        )


def downgrade() -> None:
    op.drop_index("uq_trend_alert_scope_month", table_name="trend_alerts")
    op.drop_index("ix_trend_alerts_month", table_name="trend_alerts")
    op.drop_index("ix_trend_alerts_scope_value", table_name="trend_alerts")
    op.drop_table("trend_alerts")
    op.drop_table("knowledge_sources")
