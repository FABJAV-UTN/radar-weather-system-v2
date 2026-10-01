# src/db/seed.py
"""
Crea el usuario de laboratorio (admin / admin) al arrancar el backend,
SOLO si todavía no existe. Si ya existe, no lo toca: si le cambiaste la
contraseña, se respeta.

Se desactiva con SEED_ADMIN=false (para producción).
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from src.auth.security import hash_password
from src.config import settings
from src.db.connection import AsyncSessionLocal
from src.db.models import RolUsuario, Usuario

logger = logging.getLogger(__name__)


async def crear_admin_si_falta() -> bool:
    """Devuelve True si lo creó. Nunca corta el arranque si la base no está lista."""
    if not settings.seed_admin:
        return False
    try:
        async with AsyncSessionLocal() as s:
            existe = (await s.execute(
                select(Usuario.id).where(Usuario.username == settings.seed_admin_username)
            )).scalar_one_or_none()
            if existe is not None:
                return False
            s.add(Usuario(
                username=settings.seed_admin_username,
                email=f"{settings.seed_admin_username}@admin.com",
                password_hash=hash_password(settings.seed_admin_password),
                rol=RolUsuario.ADMIN,
                activo=True,
            ))
            await s.commit()
        logger.warning(
            "Usuario de laboratorio creado: %s / %s (desactivar con SEED_ADMIN=false)",
            settings.seed_admin_username, settings.seed_admin_password,
        )
        return True
    except Exception as exc:  # p. ej. tablas sin migrar
        logger.warning("No se pudo crear el usuario de laboratorio: %s", exc)
        return False
