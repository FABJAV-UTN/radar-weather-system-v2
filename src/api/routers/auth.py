# src/api/routers/auth.py
"""
Router de autenticación: login, refresh token y logout.

Endpoints:
- POST /auth/login   → Credenciales → access + refresh token
- POST /auth/refresh → Refresh token → nuevo access token
- POST /auth/logout  → Invalida la sesión (registro en DB)
- GET  /auth/me      → Datos del usuario autenticado
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_db
from src.api.schemas.token import TokenRefreshRequest, TokenResponse
from src.api.schemas.usuario import UsuarioResponse
from src.auth.jwt import create_access_token, create_refresh_token, decode_token
from src.auth.security import verify_password
from src.db.repository import UsuarioRepository
from src.db.repository_ext import SesionRepository
import jwt

router = APIRouter(prefix="/auth", tags=["autenticación"])


class LoginRequest:
    """Request de login (username + password)."""
    pass


from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Autentica un usuario con username y password.

    Devuelve un access token (15 min) y un refresh token (7 días).
    El access token se incluye en el header Authorization: Bearer <token>.
    """
    repo = UsuarioRepository(db)
    usuario = await repo.obtener_por_username(request.username)

    if usuario is None or not usuario.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas.",
        )

    if not verify_password(request.password, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas.",
        )

    # Actualizar último login
    await repo.actualizar_ultimo_login(usuario.id)

    # Generar tokens
    access_token = create_access_token(subject=usuario.id, role=usuario.rol.value)
    refresh_token = create_refresh_token(subject=usuario.id)

    # Registrar sesión
    sesion_repo = SesionRepository(db)
    await sesion_repo.crear(
        usuario_id=usuario.id,
        refresh_token=refresh_token,
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: TokenRefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Renueva el access token usando un refresh token válido.

    El refresh token debe ser el mismo que se obtuvo en /login.
    Si el refresh token expiró o es inválido, se debe volver a logear.
    """
    try:
        payload = decode_token(request.refresh_token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expirado. Inicie sesión nuevamente.",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido.",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere un refresh token.",
        )

    usuario_id = int(payload["sub"])
    repo = UsuarioRepository(db)
    usuario = await repo.obtener_por_id(usuario_id)

    if usuario is None or not usuario.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo.",
        )

    # Verificar que la sesión existe y el refresh token coincide
    sesion_repo = SesionRepository(db)
    sesion = await sesion_repo.obtener_por_refresh_token(request.refresh_token)
    if sesion is None or not sesion.activa:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión no encontrada o revocada.",
        )

    # Generar nuevo access token (el refresh token se mantiene)
    new_access = create_access_token(subject=usuario.id, role=usuario.rol.value)

    return TokenResponse(
        access_token=new_access,
        refresh_token=request.refresh_token,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: TokenRefreshRequest,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> None:
    """
    Invalida la sesión revocando el refresh token.

    Requiere el refresh token en el body y un access token válido en el header.
    """
    sesion_repo = SesionRepository(db)
    sesion = await sesion_repo.obtener_por_refresh_token(request.refresh_token)
    if sesion:
        await sesion_repo.revocar(sesion.id)


@router.get("/me", response_model=UsuarioResponse)
async def me(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> UsuarioResponse:
    """
    Devuelve los datos del usuario autenticado.

    Requiere access token válido en el header Authorization.
    """
    usuario_id = int(current_user["sub"])
    repo = UsuarioRepository(db)
    usuario = await repo.obtener_por_id(usuario_id)

    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado.",
        )

    return UsuarioResponse.model_validate(usuario)