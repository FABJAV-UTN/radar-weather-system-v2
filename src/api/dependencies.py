# src/api/dependencies.py
"""
Dependencias de FastAPI: sesión de DB y autenticación JWT.
Se inyectan en los routers con Depends().
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.jwt import decode_token
from src.db.connection import get_session

# ── DB ────────────────────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependencia de sesión de base de datos."""
    async for session in get_session():
        yield session


# ── Auth ──────────────────────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """
    Valida el Bearer token JWT y devuelve el payload.

    Raises:
        HTTPException 401: Si el token es inválido o expiró.
    """
    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expirado.",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido.",
        )
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere un access token.",
        )
    return payload


def require_role(*roles: str):
    """
    Fábrica de dependencias para verificar roles.

    Uso:
        @router.get("/admin", dependencies=[Depends(require_role("admin"))])
    """
    async def _check(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("role") not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Se requiere rol: {roles}",
            )
        return current_user
    return _check