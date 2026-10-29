"""baseline schema

历史库（由应用启动时的 create_all 引导，或旧版 create_all + ensure_columns
迁移到当前结构）已具备全部表结构；baseline 对这类库只做版本标记，
对全新空库执行完整建表。这样旧部署无需手工 stamp 即可直接
`alembic upgrade head`，后续增量迁移从此文件接续。

Revision ID: 673175f7eda4
Revises:
Create Date: 2026-10-24 16:02:38.321350

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '673175f7eda4'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables_exist(inspector: sa.Inspector) -> bool:
    return "assessments" in inspector.get_table_names()


def upgrade() -> None:
    """Upgrade schema."""
    inspector = sa.inspect(op.get_bind())
    if _tables_exist(inspector):
        # 已由 create_all 引导的库：结构即当前 baseline，跳过建表只记录版本
        return
    op.create_table('assessments',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('scene_summary', sa.Text(), nullable=True),
    sa.Column('hazard_category', sa.String(length=128), nullable=True),
    sa.Column('risk_level', sa.Integer(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('conclusion', sa.Text(), nullable=True),
    sa.Column('evidence_json', sa.Text(), nullable=True),
    sa.Column('report_json', sa.Text(), nullable=True),
    sa.Column('followup_questions_json', sa.Text(), nullable=True),
    sa.Column('followup_used', sa.Integer(), nullable=False),
    sa.Column('confirmed', sa.Boolean(), nullable=False),
    sa.Column('rectification_status', sa.String(length=32), nullable=True),
    sa.Column('rectification_note', sa.Text(), nullable=True),
    sa.Column('rectification_score', sa.Float(), nullable=True),
    sa.Column('rectification_analysis_json', sa.Text(), nullable=True),
    sa.Column('rectification_meta_json', sa.Text(), nullable=True),
    sa.Column('rectified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_reasons_json', sa.Text(), nullable=True),
    sa.Column('human_review_json', sa.Text(), nullable=True),
    sa.Column('risk_result_json', sa.Text(), nullable=True),
    sa.Column('evidence_judge_json', sa.Text(), nullable=True),
    sa.Column('ensemble_judge_json', sa.Text(), nullable=True),
    sa.Column('multi_model_json', sa.Text(), nullable=True),
    sa.Column('disagreement_json', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('assessments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_assessments_status'), ['status'], unique=False)

    op.create_table('knowledge_documents',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('source', sa.Text(), nullable=True),
    sa.Column('version', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('content_text', sa.Text(), nullable=True),
    sa.Column('meta_json', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('assessment_images',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('assessment_id', sa.String(length=36), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('stored_path', sa.String(length=512), nullable=False),
    sa.Column('mime_type', sa.String(length=128), nullable=True),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('image_kind', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['assessment_id'], ['assessments.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('assessment_images', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_assessment_images_assessment_id'), ['assessment_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    inspector = sa.inspect(op.get_bind())
    if not _tables_exist(inspector):
        return
    with op.batch_alter_table('assessment_images', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_assessment_images_assessment_id'))

    op.drop_table('assessment_images')
    op.drop_table('knowledge_documents')
    with op.batch_alter_table('assessments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_assessments_status'))

    op.drop_table('assessments')
