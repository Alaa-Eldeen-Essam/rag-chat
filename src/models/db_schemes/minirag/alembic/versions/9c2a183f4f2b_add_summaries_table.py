"""add summaries table

Revision ID: 9c2a183f4f2b
Revises: 517b29f90ead
Create Date: 2025-11-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9c2a183f4f2b'
down_revision: Union[str, None] = '20241107_conversation_tags'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'summaries',
        sa.Column('summary_id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.project_id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('asset_id', sa.Integer(), sa.ForeignKey('assets.asset_id'), nullable=True),
        sa.Column('request_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('chunk_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('chunk_count', sa.Integer(), nullable=False),
        sa.Column('summary_text', sa.Text(), nullable=False),
        sa.Column('prompt_text', sa.Text(), nullable=True),
        sa.Column('max_output_tokens', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    )
    op.create_index('ix_summaries_project_id', 'summaries', ['project_id'])
    op.create_index('ix_summaries_user_id', 'summaries', ['user_id'])
    op.create_index('ix_summaries_asset_id', 'summaries', ['asset_id'])


def downgrade() -> None:
    op.drop_index('ix_summaries_asset_id', table_name='summaries')
    op.drop_index('ix_summaries_user_id', table_name='summaries')
    op.drop_index('ix_summaries_project_id', table_name='summaries')
    op.drop_table('summaries')
