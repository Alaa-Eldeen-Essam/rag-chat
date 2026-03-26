"""add pinned flag to conversations

Revision ID: 20250102_add_conversation_pin
Revises: 20251109_add_user_department
Create Date: 2025-01-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20250102_add_conversation_pin"
down_revision: Union[str, None] = "20251109_add_user_department"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_conversations",
        sa.Column(
          "conversation_is_pinned",
          sa.Boolean(),
          nullable=False,
          server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_conversations", "conversation_is_pinned")
