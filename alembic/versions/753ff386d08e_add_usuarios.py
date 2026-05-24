"""add_usuarios

Revision ID: 753ff386d08e
Revises: 2752e96026f6
Create Date: 2026-05-23 21:31:56.576971

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '753ff386d08e'
down_revision: Union[str, Sequence[str], None] = '2752e96026f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crea la tabla radar.usuarios."""
    op.create_table(
        'usuarios',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('email', sa.String(length=100), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('rol', sa.Enum('admin', 'operador', 'visualizador', name='enum_rol_usuario'), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False),
        sa.Column('ultimo_login', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint("rol IN ('admin', 'operador', 'visualizador')", name='ck_usuarios_rol'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email', name='uq_usuarios_email'),
        sa.UniqueConstraint('username', name='uq_usuarios_username'),
        schema='radar'
    )
    op.create_index(op.f('ix_radar_usuarios_activo'), 'usuarios', ['activo'], unique=False, schema='radar')
    op.create_index(op.f('ix_radar_usuarios_email'), 'usuarios', ['email'], unique=True, schema='radar')
    op.create_index(op.f('ix_radar_usuarios_username'), 'usuarios', ['username'], unique=True, schema='radar')


def downgrade() -> None:
    """Elimina la tabla radar.usuarios."""
    op.drop_index(op.f('ix_radar_usuarios_username'), table_name='usuarios', schema='radar')
    op.drop_index(op.f('ix_radar_usuarios_email'), table_name='usuarios', schema='radar')
    op.drop_index(op.f('ix_radar_usuarios_activo'), table_name='usuarios', schema='radar')
    op.drop_table('usuarios', schema='radar')
