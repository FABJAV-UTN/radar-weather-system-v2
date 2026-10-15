"""add_archivo_intentos

Agrega radar.intentos_descarga.archivo: los bytes de lo que se descargó en un
intento RECHAZADO (GIF incompleto, o completo pero sin hora legible por OCR),
para poder ver después por qué se rechazó. En los intentos positivos queda
NULL (la imagen ya está en imagenes_radar.raw_data).

Mantenimiento: los archivos viejos se vacían (la fila de auditoría queda) con
    docker compose exec backend uv run --no-dev python -m src.scripts.limpiar_intentos --aplicar

Revision ID: b7e2d4c91a05
Revises: 8f3c1a2b9d47
Create Date: 2026-10-15 14:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e2d4c91a05'
down_revision: Union[str, Sequence[str], None] = '8f3c1a2b9d47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'intentos_descarga',
        sa.Column('archivo', sa.LargeBinary(), nullable=True),
        schema='radar',
    )


def downgrade() -> None:
    op.drop_column('intentos_descarga', 'archivo', schema='radar')
