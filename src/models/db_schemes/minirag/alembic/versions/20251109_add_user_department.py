"""add department column to users

Revision ID: 20251109_add_user_department
Revises: 9c2a183f4f2b
Create Date: 2025-11-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20251109_add_user_department"
down_revision: Union[str, None] = "9c2a183f4f2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "department",
            sa.String(),
            nullable=False,
            server_default="Global",
        ),
    )
    op.create_index("ix_users_department", "users", ["department"])


def downgrade() -> None:
    op.drop_index("ix_users_department", table_name="users")
    op.drop_column("users", "department")

