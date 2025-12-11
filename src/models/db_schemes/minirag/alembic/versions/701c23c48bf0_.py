"""empty message

Revision ID: 701c23c48bf0
Revises: 20250104_change_asset_department_to_list, 20260103_retrieved_assets
Create Date: 2025-12-11 06:59:12.063581

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '701c23c48bf0'
down_revision: Union[str, None] = ('20250104_asset_department_list', '20260103_retrieved_assets')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
