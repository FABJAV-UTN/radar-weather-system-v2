"""Pydantic models para el tracking de tormentas (Subsistema 2)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class TrackResumen(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    estado: str
    inicio: datetime
    fin: datetime
    duracion_min: float | None = None
    n_celdas: int
    distancia_total_km: float | None = None
    desplazamiento_neto_km: float | None = None
    vel_media_kmh: float | None = None
    vel_max_kmh: float | None = None
    direccion_media_deg: float | None = None
    area_max_km2: float | None = None
    dbz_max: int | None = None
    trayectoria: dict[str, Any] | None = None   # GeoJSON LineString en EPSG:4326


class TrackListaResponse(BaseModel):
    desde: date
    hasta: date
    total: int
    total_en_base: int        # para distinguir "no hay en esas fechas" de "todavía no se corrió"
    items: list[TrackResumen]


class CeldaResumen(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    imagen_id: int
    fecha_hora: datetime
    lat: float | None = None
    lon: float | None = None
    area_km2: float
    area_nucleo_km2: float | None = None
    dbz_max: int
    dbz_medio: float
    distancia_m: float | None = None
    velocidad_kmh: float | None = None
    direccion_deg: float | None = None
    geo_corregida: bool
    poligono: dict[str, Any] | None = None      # GeoJSON en EPSG:4326


class TrackDetalle(TrackResumen):
    ejecucion_id: int
    celdas: list[CeldaResumen]
