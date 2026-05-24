# src/api/schemas/token.py
"""Pydantic models para autenticación JWT."""
from pydantic import BaseModel


class TokenResponse(BaseModel):
    """Respuesta del endpoint de login."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefreshRequest(BaseModel):
    """Request para renovar el access token."""

    refresh_token: str


class TokenPayload(BaseModel):
    """Payload decodificado de un JWT."""

    sub: str
    role: str
    type: str