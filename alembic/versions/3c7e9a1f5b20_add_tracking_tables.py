"""add_tracking_tables

F1 del Subsistema 2: tablas del tracking de tormentas.

  ejecuciones_tracking · tracks_tormenta · celdas_tormenta · relaciones_celdas

Geometrías en EPSG:5344 (POSGAR 2007 / faja 2). El DDL es el mismo que se
validó contra PostgreSQL 16 + PostGIS 3.4 y figura en
PROYECTO CLIMA/SUBSISTEMA 2/F1/F1_modelo_datos_tracking.pdf (anexo A).

Revision ID: 3c7e9a1f5b20
Revises: 8f3c1a2b9d47
Create Date: 2026-10-01 16:40:00

"""
from typing import Sequence, Union

from alembic import op


revision: str = '3c7e9a1f5b20'
down_revision: Union[str, Sequence[str], None] = '8f3c1a2b9d47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DDL = r"""
CREATE EXTENSION IF NOT EXISTS postgis;

-- 1. Ejecuciones: con qué parámetros y cuándo se calculó cada tracking
CREATE TABLE radar.ejecuciones_tracking (
    id                serial       PRIMARY KEY,
    modo              varchar(10)  NOT NULL,
    rango_desde       timestamp,
    rango_hasta       timestamp,
    parametros        jsonb        NOT NULL,          -- D1..D14 usados
    version_algoritmo varchar(20)  NOT NULL,
    estado            varchar(12)  NOT NULL DEFAULT 'en_curso',
    n_imagenes        integer,
    n_celdas          integer,
    n_tracks          integer,
    mensaje           text,
    iniciada_en       timestamp    NOT NULL DEFAULT now(),
    finalizada_en     timestamp,
    CONSTRAINT ck_ejecuciones_modo   CHECK (modo IN ('auto', 'manual')),
    CONSTRAINT ck_ejecuciones_estado CHECK (estado IN ('en_curso', 'ok', 'error')),
    CONSTRAINT ck_ejecuciones_rango  CHECK (rango_desde IS NULL OR rango_hasta IS NULL
                                            OR rango_desde < rango_hasta)
);

-- 2. Tracks: una tormenta con identidad propia y sus totales
CREATE TABLE radar.tracks_tormenta (
    id                       serial       PRIMARY KEY,
    codigo                   varchar(20)  NOT NULL,   -- T-AAAAMMDD-NNN
    ejecucion_id             integer      NOT NULL
        REFERENCES radar.ejecuciones_tracking (id) ON DELETE CASCADE,
    estado                   varchar(10)  NOT NULL DEFAULT 'activo',
    inicio                   timestamp    NOT NULL,
    fin                      timestamp    NOT NULL,
    duracion_min             real,
    n_celdas                 integer      NOT NULL DEFAULT 0,
    distancia_total_km       real,
    desplazamiento_neto_km   real,
    vel_media_kmh            real,
    vel_max_kmh              real,
    direccion_media_deg      real,
    area_max_km2             real,
    dbz_max                  smallint,
    trayectoria              geometry(LineString, 5344),
    created_at               timestamp    NOT NULL DEFAULT now(),
    updated_at               timestamp    NOT NULL DEFAULT now(),
    CONSTRAINT uq_tracks_codigo     UNIQUE (codigo),
    CONSTRAINT ck_tracks_estado     CHECK (estado IN ('activo', 'cerrado', 'espurio')),
    CONSTRAINT ck_tracks_tiempo     CHECK (fin >= inicio),
    CONSTRAINT ck_tracks_direccion  CHECK (direccion_media_deg IS NULL
                                           OR (direccion_media_deg >= 0 AND direccion_media_deg < 360)),
    CONSTRAINT ck_tracks_codigo     CHECK (codigo ~ '^T-[0-9]{8}-[0-9]{3,}$')
);
CREATE INDEX ix_radar_tracks_tormenta_ejecucion  ON radar.tracks_tormenta (ejecucion_id);
CREATE INDEX ix_radar_tracks_tormenta_periodo    ON radar.tracks_tormenta (inicio, fin);
CREATE INDEX ix_radar_tracks_tormenta_estado     ON radar.tracks_tormenta (estado);
CREATE INDEX gx_radar_tracks_tormenta_trayectoria ON radar.tracks_tormenta USING gist (trayectoria);

-- 3. Celdas: un eco ≥ D1 dBZ en una imagen (la "capa de puntos")
CREATE TABLE radar.celdas_tormenta (
    id               serial       PRIMARY KEY,
    imagen_id        integer      NOT NULL
        REFERENCES radar.imagenes_radar (id) ON DELETE CASCADE,
    ejecucion_id     integer      NOT NULL
        REFERENCES radar.ejecuciones_tracking (id) ON DELETE CASCADE,
    track_id         integer
        REFERENCES radar.tracks_tormenta (id) ON DELETE SET NULL,
    numero           smallint     NOT NULL,           -- etiqueta dentro de la imagen
    fecha_hora       timestamp    NOT NULL,           -- copia de imagenes_radar.fecha_hora
    centroide        geometry(Point, 5344)        NOT NULL,
    poligono         geometry(MultiPolygon, 5344) NOT NULL,
    x_m              double precision GENERATED ALWAYS AS (ST_X(centroide)) STORED,
    y_m              double precision GENERATED ALWAYS AS (ST_Y(centroide)) STORED,
    lon              double precision GENERATED ALWAYS AS (ST_X(ST_Transform(centroide, 4326))) STORED,
    lat              double precision GENERATED ALWAYS AS (ST_Y(ST_Transform(centroide, 4326))) STORED,
    n_pixeles        integer      NOT NULL,
    area_km2         real         NOT NULL,
    area_nucleo_km2  real,                            -- píxeles ≥ D2 (45 dBZ)
    dbz_max          smallint     NOT NULL,
    dbz_medio        real         NOT NULL,
    geo_corregida    boolean      NOT NULL DEFAULT false,  -- D13 aplicado a la imagen
    -- cinemática del paso desde la celda anterior del mismo track
    dt_min           real,
    distancia_m      real,
    velocidad_kmh    real,
    direccion_deg    real,                            -- hacia dónde va, desde el norte
    delta_area_km2   real,
    CONSTRAINT uq_celdas_imagen_numero UNIQUE (ejecucion_id, imagen_id, numero),
    CONSTRAINT ck_celdas_area        CHECK (area_km2 > 0 AND n_pixeles > 0),
    CONSTRAINT ck_celdas_nucleo      CHECK (area_nucleo_km2 IS NULL
                                            OR (area_nucleo_km2 >= 0 AND area_nucleo_km2 <= area_km2)),
    CONSTRAINT ck_celdas_dbz         CHECK (dbz_max BETWEEN 0 AND 80 AND dbz_medio <= dbz_max),
    CONSTRAINT ck_celdas_velocidad   CHECK (velocidad_kmh IS NULL OR velocidad_kmh >= 0),
    CONSTRAINT ck_celdas_direccion   CHECK (direccion_deg IS NULL
                                            OR (direccion_deg >= 0 AND direccion_deg < 360))
);
CREATE INDEX ix_radar_celdas_tormenta_track_fecha ON radar.celdas_tormenta (track_id, fecha_hora);
CREATE INDEX ix_radar_celdas_tormenta_fecha       ON radar.celdas_tormenta (fecha_hora);
CREATE INDEX ix_radar_celdas_tormenta_imagen      ON radar.celdas_tormenta (imagen_id);
CREATE INDEX gx_radar_celdas_tormenta_centroide   ON radar.celdas_tormenta USING gist (centroide);
CREATE INDEX gx_radar_celdas_tormenta_poligono    ON radar.celdas_tormenta USING gist (poligono);

-- 4. Relaciones: el grafo de asociación entre imágenes consecutivas
CREATE TABLE radar.relaciones_celdas (
    celda_origen_id   integer      NOT NULL
        REFERENCES radar.celdas_tormenta (id) ON DELETE CASCADE,
    celda_destino_id  integer      NOT NULL
        REFERENCES radar.celdas_tormenta (id) ON DELETE CASCADE,
    tipo              varchar(12)  NOT NULL,
    metodo            varchar(12)  NOT NULL,
    score             real         NOT NULL,
    CONSTRAINT pk_relaciones_celdas PRIMARY KEY (celda_origen_id, celda_destino_id),
    CONSTRAINT ck_relaciones_tipo   CHECK (tipo IN ('continuacion', 'division', 'fusion')),
    CONSTRAINT ck_relaciones_metodo CHECK (metodo IN ('solapamiento', 'distancia')),
    CONSTRAINT ck_relaciones_score  CHECK (score >= 0 AND score <= 1),
    CONSTRAINT ck_relaciones_distintas CHECK (celda_origen_id <> celda_destino_id)
);
CREATE INDEX ix_radar_relaciones_celdas_destino ON radar.relaciones_celdas (celda_destino_id);
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS radar.relaciones_celdas, radar.celdas_tormenta, "
        "radar.tracks_tormenta, radar.ejecuciones_tracking"
    )
