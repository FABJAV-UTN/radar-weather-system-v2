# src/db/models_tracking.py
"""
Modelos del tracking de tormentas (Subsistema 2, fase F1).

Reflejan la migración 3c7e9a1f5b20 (esquema `radar`). Diseño completo en
PROYECTO CLIMA/SUBSISTEMA 2/F1/F1_modelo_datos_tracking.pdf.

- Geometrías en EPSG:5344 (POSGAR 2007 / Argentina faja 2).
- x_m, y_m, lon, lat son columnas GENERADAS por la base a partir del
  centroide: nunca se escriben desde Python.
- spatial_index=False: los índices GiST los crea la migración con nombre
  propio (gx_radar_*), no GeoAlchemy2.
"""
from __future__ import annotations

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    REAL as Real,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models import Base

SRID = 5344

_GEOM = dict(srid=SRID, spatial_index=False)


class EjecucionTracking(Base):
    """Una corrida del tracking: modo, rango, parámetros y resultado."""

    __tablename__ = "ejecuciones_tracking"
    __table_args__ = (
        CheckConstraint("modo IN ('auto', 'manual')", name="ck_ejecuciones_modo"),
        CheckConstraint("estado IN ('en_curso', 'ok', 'error')", name="ck_ejecuciones_estado"),
        CheckConstraint(
            "rango_desde IS NULL OR rango_hasta IS NULL OR rango_desde < rango_hasta",
            name="ck_ejecuciones_rango",
        ),
        {"schema": "radar"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    modo: Mapped[str] = mapped_column(String(10), nullable=False)
    rango_desde: Mapped[datetime | None] = mapped_column(DateTime)
    rango_hasta: Mapped[datetime | None] = mapped_column(DateTime)
    parametros: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version_algoritmo: Mapped[str] = mapped_column(String(20), nullable=False)
    estado: Mapped[str] = mapped_column(String(12), nullable=False, server_default="en_curso")
    n_imagenes: Mapped[int | None] = mapped_column(Integer)
    n_celdas: Mapped[int | None] = mapped_column(Integer)
    n_tracks: Mapped[int | None] = mapped_column(Integer)
    mensaje: Mapped[str | None] = mapped_column(Text)
    iniciada_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    finalizada_en: Mapped[datetime | None] = mapped_column(DateTime)


class TrackTormenta(Base):
    """Una tormenta con identidad propia a lo largo del tiempo y sus totales."""

    __tablename__ = "tracks_tormenta"
    __table_args__ = (
        UniqueConstraint("codigo", name="uq_tracks_codigo"),
        CheckConstraint("estado IN ('activo', 'cerrado', 'espurio')", name="ck_tracks_estado"),
        CheckConstraint("fin >= inicio", name="ck_tracks_tiempo"),
        CheckConstraint(
            "direccion_media_deg IS NULL OR (direccion_media_deg >= 0 AND direccion_media_deg < 360)",
            name="ck_tracks_direccion",
        ),
        CheckConstraint("codigo ~ '^T-[0-9]{8}-[0-9]{3,}$'", name="ck_tracks_codigo"),
        {"schema": "radar"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    ejecucion_id: Mapped[int] = mapped_column(
        ForeignKey("radar.ejecuciones_tracking.id", ondelete="CASCADE"), nullable=False, index=True
    )
    estado: Mapped[str] = mapped_column(String(10), nullable=False, server_default="activo")
    inicio: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    fin: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    duracion_min: Mapped[float | None] = mapped_column(Real)
    n_celdas: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    distancia_total_km: Mapped[float | None] = mapped_column(Real)
    desplazamiento_neto_km: Mapped[float | None] = mapped_column(Real)
    vel_media_kmh: Mapped[float | None] = mapped_column(Real)
    vel_max_kmh: Mapped[float | None] = mapped_column(Real)
    direccion_media_deg: Mapped[float | None] = mapped_column(Real)
    area_max_km2: Mapped[float | None] = mapped_column(Real)
    dbz_max: Mapped[int | None] = mapped_column(SmallInteger)
    trayectoria = mapped_column(Geometry("LINESTRING", **_GEOM))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CeldaTormenta(Base):
    """Un eco ≥ D1 dBZ en una imagen (la capa de puntos del plan de trabajo)."""

    __tablename__ = "celdas_tormenta"
    __table_args__ = (
        UniqueConstraint("ejecucion_id", "imagen_id", "numero", name="uq_celdas_imagen_numero"),
        CheckConstraint("area_km2 > 0 AND n_pixeles > 0", name="ck_celdas_area"),
        CheckConstraint(
            "area_nucleo_km2 IS NULL OR (area_nucleo_km2 >= 0 AND area_nucleo_km2 <= area_km2)",
            name="ck_celdas_nucleo",
        ),
        CheckConstraint("dbz_max BETWEEN 0 AND 80 AND dbz_medio <= dbz_max", name="ck_celdas_dbz"),
        CheckConstraint("velocidad_kmh IS NULL OR velocidad_kmh >= 0", name="ck_celdas_velocidad"),
        CheckConstraint(
            "direccion_deg IS NULL OR (direccion_deg >= 0 AND direccion_deg < 360)",
            name="ck_celdas_direccion",
        ),
        {"schema": "radar"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    imagen_id: Mapped[int] = mapped_column(
        ForeignKey("radar.imagenes_radar.id", ondelete="CASCADE"), nullable=False
    )
    ejecucion_id: Mapped[int] = mapped_column(
        ForeignKey("radar.ejecuciones_tracking.id", ondelete="CASCADE"), nullable=False
    )
    track_id: Mapped[int | None] = mapped_column(
        ForeignKey("radar.tracks_tormenta.id", ondelete="SET NULL")
    )
    numero: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    fecha_hora: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    centroide = mapped_column(Geometry("POINT", **_GEOM), nullable=False)
    poligono = mapped_column(Geometry("MULTIPOLYGON", **_GEOM), nullable=False)
    x_m: Mapped[float | None] = mapped_column(Float, Computed("ST_X(centroide)", persisted=True))
    y_m: Mapped[float | None] = mapped_column(Float, Computed("ST_Y(centroide)", persisted=True))
    lon: Mapped[float | None] = mapped_column(
        Float, Computed("ST_X(ST_Transform(centroide, 4326))", persisted=True)
    )
    lat: Mapped[float | None] = mapped_column(
        Float, Computed("ST_Y(ST_Transform(centroide, 4326))", persisted=True)
    )
    n_pixeles: Mapped[int] = mapped_column(Integer, nullable=False)
    area_km2: Mapped[float] = mapped_column(Real, nullable=False)
    area_nucleo_km2: Mapped[float | None] = mapped_column(Real)
    dbz_max: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    dbz_medio: Mapped[float] = mapped_column(Real, nullable=False)
    geo_corregida: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    dt_min: Mapped[float | None] = mapped_column(Real)
    distancia_m: Mapped[float | None] = mapped_column(Real)
    velocidad_kmh: Mapped[float | None] = mapped_column(Real)
    direccion_deg: Mapped[float | None] = mapped_column(Real)
    delta_area_km2: Mapped[float | None] = mapped_column(Real)


class RelacionCeldas(Base):
    """Arista del grafo: una celda de t−1 continúa, se divide o se fusiona en t."""

    __tablename__ = "relaciones_celdas"
    __table_args__ = (
        PrimaryKeyConstraint("celda_origen_id", "celda_destino_id", name="pk_relaciones_celdas"),
        CheckConstraint("tipo IN ('continuacion', 'division', 'fusion')", name="ck_relaciones_tipo"),
        CheckConstraint("metodo IN ('solapamiento', 'distancia')", name="ck_relaciones_metodo"),
        CheckConstraint("score >= 0 AND score <= 1", name="ck_relaciones_score"),
        CheckConstraint("celda_origen_id <> celda_destino_id", name="ck_relaciones_distintas"),
        {"schema": "radar"},
    )

    celda_origen_id: Mapped[int] = mapped_column(
        ForeignKey("radar.celdas_tormenta.id", ondelete="CASCADE"), nullable=False
    )
    celda_destino_id: Mapped[int] = mapped_column(
        ForeignKey("radar.celdas_tormenta.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tipo: Mapped[str] = mapped_column(String(12), nullable=False)
    metodo: Mapped[str] = mapped_column(String(12), nullable=False)
    score: Mapped[float] = mapped_column(Real, nullable=False)
