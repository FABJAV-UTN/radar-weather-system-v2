# src/api/schemas/imagen.py
"""Pydantic models para el recurso ImagenRadar."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ImagenResumen(BaseModel):
    """Resumen de una imagen (respuesta de listado)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha_hora: datetime
    origen: str
    estado: str
    tiene_marco: bool
    score_match: float | None = None
    crs: str | None = None
    fecha_procesamiento: datetime | None = None
    created_at: datetime


class ImagenDetalle(ImagenResumen):
    """Detalle completo de una imagen (respuesta individual)."""

    transform_affine: str | None = None


class ImagenListaResponse(BaseModel):
    """Respuesta paginada de listado de imágenes."""

    total: int
    limit: int
    offset: int
    items: list[ImagenResumen]


class ProcesarURLRequest(BaseModel):
    """Request para ejecutar el pipeline desde la URL DACC."""

    url: str | None = Field(
        default=None,
        description="URL alternativa. Si se omite, se usa la URL DACC por defecto.",
    )


class ProcesarLocalRequest(BaseModel):
    """Request para ejecutar el pipeline desde un archivo local."""

    file_path: str = Field(
        ...,
        description="Ruta absoluta al archivo PNG o GIF en el servidor.",
    )


class PipelineResponse(BaseModel):
    """Respuesta del pipeline tras procesar una imagen."""

    imagen_id: int
    exito: bool
    mensaje_error: str = ""
    pixeles_originales: int = 0
    pixeles_limpios: int = 0
    pixeles_rellenados: int = 0
    pixeles_perdidos: int = 0
    error_relleno_pct: float = 0.0
    score_match: float = 0.0
    tiene_marco: bool = False