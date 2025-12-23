"""Change asset_department to list

Revision ID: 20250104_change_asset_department_to_list
Revises: 0e89cda845c7
Create Date: 2025-01-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20250104_asset_department_list'
down_revision: Union[str, None] = '0e89cda845c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Convert asset_department from String to JSONB (list)
    op.alter_column('assets', 'asset_department',
                    type_=postgresql.JSONB(astext_type=sa.Text()),
                    postgresql_using='CASE WHEN asset_department IS NULL THEN NULL ELSE json_build_array(asset_department) END',
                    nullable=True)


def downgrade() -> None:
    # Convert asset_department from JSONB back to String
    op.alter_column('assets', 'asset_department',
                    type_=sa.String(),
                    postgresql_using="CASE WHEN asset_department IS NULL THEN NULL ELSE asset_department->>0 END",
                    nullable=True)
