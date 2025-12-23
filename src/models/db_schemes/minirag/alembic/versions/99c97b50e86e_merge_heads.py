"""merge heads

Revision ID: 99c97b50e86e
Revises: 20250102_add_conversation_pin, 6ea278d7f170
Create Date: 2025-11-30 11:14:56.253218

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '99c97b50e86e'
down_revision: Union[str, None] = ('20250102_add_conversation_pin', '6ea278d7f170')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
