"""add_sesiones

Revision ID: 4695d1c4d543
Revises: 753ff386d08e
Create Date: 2026-05-23 22:52:15.394955

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '4695d1c4d543'
down_revision: Union[str, Sequence[str], None] = '753ff386d08e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sesiones',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('refresh_token', sa.String(length=500), nullable=False),
        sa.Column('activa', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('revocada_en', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('refresh_token'),
        sa.ForeignKeyConstraint(['usuario_id'], ['radar.usuarios.id'], ondelete='CASCADE'),
        schema='radar',
    )


def downgrade() -> None:
    op.drop_table('sesiones', schema='radar')