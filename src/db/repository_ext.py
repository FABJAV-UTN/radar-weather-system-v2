# src/db/repository_ext.py
"""
Extensiones del patrón Repository:
- SesionRepository: gestión de sesiones JWT.
- Método eliminar() para UsuarioRepository.

Importar junto con repository.py:
    from src.db.repository import UsuarioRepository, ...
    from src.db.repository_ext import SesionRepository
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.sesion_model import Sesion


class SesionRepository:
    """Repositorio para radar.sesiones."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def crear(self, usuario_id: int, refresh_token: str) -> Sesion:
        """Registra una nueva sesión activa."""
        sesion = Sesion(
            usuario_id=usuario_id,
            refresh_token=refresh_token,
            activa=True,
        )
        self._session.add(sesion)
        await self._session.flush()
        return sesion

    async def obtener_por_refresh_token(self, refresh_token: str) -> Sesion | None:
        """Busca una sesión por su refresh token."""
        result = await self._session.execute(
            select(Sesion).where(Sesion.refresh_token == refresh_token)
        )
        return result.scalar_one_or_none()

    async def revocar(self, sesion_id: int) -> None:
        """Revoca una sesión, marcándola como inactiva."""
        await self._session.execute(
            update(Sesion)
            .where(Sesion.id == sesion_id)
            .values(activa=False, revocada_en=datetime.utcnow())
        )

    async def revocar_todas_de_usuario(self, usuario_id: int) -> None:
        """Revoca todas las sesiones activas de un usuario (logout global)."""
        await self._session.execute(
            update(Sesion)
            .where(Sesion.usuario_id == usuario_id, Sesion.activa.is_(True))
            .values(activa=False, revocada_en=datetime.utcnow())
        )

    async def limpiar_expiradas(self) -> int:
        """
        Elimina sesiones revocadas de más de 30 días.
        Para ejecutar periódicamente como tarea de mantenimiento.
        """
        result = await self._session.execute(
            delete(Sesion).where(
                Sesion.activa.is_(False),
            )
        )
        return result.rowcount