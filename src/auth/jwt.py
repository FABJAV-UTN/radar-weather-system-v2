# src/auth/jwt.py
"""
Creación y verificación de tokens JWT.
Access token de corta duración + Refresh token de larga duración.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from src.config import settings


def create_access_token(subject: str | int, role: str) -> str:
    """
    Genera un access token JWT con expiración corta.

    Args:
        subject: Identificador del usuario (ID o username).
        role: Rol del usuario ('admin', 'operador', 'visualizador').

    Returns:
        Token JWT firmado.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {
        "sub": str(subject),
        "role": role,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(subject: str | int) -> str:
    """
    Genera un refresh token JWT con expiración larga.

    Args:
        subject: Identificador del usuario.

    Returns:
        Token JWT de refresco firmado.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    payload = {
        "sub": str(subject),
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict:
    """
    Decodifica y valida un token JWT.

    Args:
        token: Token JWT como string.

    Returns:
        Payload decodificado.

    Raises:
        jwt.ExpiredSignatureError: Si el token expiró.
        jwt.InvalidTokenError: Si el token es inválido.
    """
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])