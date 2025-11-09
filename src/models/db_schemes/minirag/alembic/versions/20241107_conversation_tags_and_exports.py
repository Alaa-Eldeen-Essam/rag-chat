"""placeholder for missing conversation tags migration

Revision ID: 20241107_conversation_tags
Revises: 517b29f90ead
Create Date: 2025-11-08 12:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '20241107_conversation_tags'
down_revision: Union[str, None] = '517b29f90ead'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Historical migration was removed upstream; this placeholder keeps revision history aligned.
    pass


def downgrade() -> None:
    pass
