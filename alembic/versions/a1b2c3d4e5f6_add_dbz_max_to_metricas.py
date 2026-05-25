"""add dbz_max to metricas

Revision ID: a1b2c3d4e5f6
Revises: 4695d1c4d543
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "6077fff6a14e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agrega la columna dbz_max (Float nullable) a radar.metricas_procesamiento."""
    op.add_column(
        "metricas_procesamiento",
        sa.Column("dbz_max", sa.Float(), nullable=True),
        schema="radar",
    )


def downgrade() -> None:
    """Elimina la columna dbz_max de radar.metricas_procesamiento."""
    op.drop_column("metricas_procesamiento", "dbz_max", schema="radar")
