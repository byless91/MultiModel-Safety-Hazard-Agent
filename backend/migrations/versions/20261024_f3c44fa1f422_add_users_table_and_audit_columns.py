"""add users table and audit columns

Revision ID: f3c44fa1f422
Revises: d6b3c739463f
Create Date: 2026-10-24 16:49:58.190918

调和路径守卫：create_all 半引导的库可能已带 users 表或部分审计列，
每段操作独立判断，只补真正缺失的部分。

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3c44fa1f422'
down_revision: Union[str, Sequence[str], None] = 'd6b3c739463f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables(inspector) -> set:
    return set(inspector.get_table_names())


def _columns(inspector, table: str) -> set:
    return {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    """Upgrade schema."""
    inspector = sa.inspect(op.get_bind())

    if "users" not in _tables(inspector):
        op.create_table('users',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('password_hash', sa.String(length=128), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('disabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.create_index(
                batch_op.f('ix_users_username'), ['username'], unique=True
            )

    existing = _columns(inspector, "assessments")
    missing = [name for name in ("confirmed_by_id", "confirmed_by_name") if name not in existing]
    if missing:
        with op.batch_alter_table('assessments', schema=None) as batch_op:
            for name in missing:
                if name == "confirmed_by_id":
                    batch_op.add_column(sa.Column('confirmed_by_id', sa.String(length=36), nullable=True))
                else:
                    batch_op.add_column(sa.Column('confirmed_by_name', sa.String(length=64), nullable=True))
        if "confirmed_by_id" in missing:
            # SQLite batch 重建后索引随列存在性判断，避免重复创建
            index_names = {
                row["name"]
                for row in sa.inspect(op.get_bind()).get_indexes("assessments")
            }
            if "ix_assessments_confirmed_by_id" not in index_names:
                with op.batch_alter_table('assessments', schema=None) as batch_op:
                    batch_op.create_index(
                        batch_op.f('ix_assessments_confirmed_by_id'),
                        ['confirmed_by_id'],
                        unique=False,
                    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "assessments" in _tables(inspector):
        existing = _columns(inspector, "assessments")
        if "confirmed_by_id" in existing or "confirmed_by_name" in existing:
            with op.batch_alter_table('assessments', schema=None) as batch_op:
                if "confirmed_by_id" in existing:
                    batch_op.drop_column('confirmed_by_id')
                if "confirmed_by_name" in existing:
                    batch_op.drop_column('confirmed_by_name')

    if "users" in _tables(inspector):
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_users_username'))
        op.drop_table('users')
