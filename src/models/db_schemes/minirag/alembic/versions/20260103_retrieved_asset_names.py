"""add retrieved_asset_names to chat_history

Revision ID: 20260103_retrieved_assets
Revises: 99c97b50e86e
Create Date: 2026-01-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260103_retrieved_assets"
down_revision: Union[str, None] = "99c97b50e86e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_history",
        sa.Column(
            "retrieved_asset_names",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_history", "retrieved_asset_names")
