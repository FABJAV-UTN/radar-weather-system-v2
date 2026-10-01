"""add_hash_raw

Agrega imagenes_radar.hash_raw (MD5 de raw_data) para rechazar imágenes
con exactamente el mismo contenido aunque tengan otro nombre u hora.
Completa el hash de las filas existentes.

El índice NO es único: puede haber duplicados viejos en la base. Para
borrarlos: python -m src.scripts.limpiar_duplicados --aplicar

Revision ID: 8f3c1a2b9d47
Revises: 25c065eb73d4
Create Date: 2026-10-01 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8f3c1a2b9d47'
down_revision: Union[str, Sequence[str], None] = '25c065eb73d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'imagenes_radar',
        sa.Column('hash_raw', sa.String(length=32), nullable=True),
        schema='radar',
    )
    op.execute(
        "UPDATE radar.imagenes_radar SET hash_raw = md5(raw_data) "
        "WHERE raw_data IS NOT NULL AND hash_raw IS NULL"
    )
    op.create_index(
        op.f('ix_radar_imagenes_radar_hash_raw'),
        'imagenes_radar', ['hash_raw'], unique=False, schema='radar',
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_radar_imagenes_radar_hash_raw'), table_name='imagenes_radar', schema='radar')
    op.drop_column('imagenes_radar', 'hash_raw', schema='radar')
