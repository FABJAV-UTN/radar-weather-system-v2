# src/api/schemas/usuario.py
"""Pydantic models para el recurso Usuario."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UsuarioResponse(BaseModel):
    """Respuesta de usuario (sin password_hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    rol: str
    activo: bool
    ultimo_login: datetime | None = None
    created_at: datetime


class UsuarioListaResponse(BaseModel):
    """Respuesta paginada de listado de usuarios."""

    total: int
    limit: int
    offset: int
    items: list[UsuarioResponse]


class CrearUsuarioRequest(BaseModel):
    """Request para crear un usuario nuevo."""

    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    email: str = Field(..., max_length=100)
    password: str = Field(..., min_length=8, max_length=128)
    rol: str = Field(default="visualizador", pattern=r"^(admin|operador|visualizador)$")


class CambiarRolRequest(BaseModel):
    """Request para cambiar el rol de un usuario."""

    rol: str = Field(..., pattern=r"^(admin|operador|visualizador)$")


class CambiarEstadoRequest(BaseModel):
    """Request para activar/desactivar un usuario."""

    activo: bool