# src/db/repository_tracking.py
"""
Repositorios del tracking de tormentas (Subsistema 2).

Única capa que escribe SQL sobre las tablas de tracking, igual que
repository.py para el Subsistema 1. El detector y el tracker trabajan con
datos en memoria y le piden a estos repositorios que persistan.

Geometrías: se reciben como WKT en EPSG:5344 (o x/y en metros para el
centroide) y se devuelven como GeoJSON en EPSG:4326, que es lo que espera
un mapa web.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models_tracking import (
    SRID,
    CeldaTormenta,
    EjecucionTracking,
    RelacionCeldas,
    TrackTormenta,
)

TIPOS_RELACION = ("continuacion", "division", "fusion")


# ─────────────────────────────────────────────────────────────────────────────
# Ejecuciones
# ─────────────────────────────────────────────────────────────────────────────

class EjecucionTrackingRepository:
    """radar.ejecuciones_tracking: una corrida del tracking."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def crear(
        self,
        modo: str,
        parametros: dict,
        version_algoritmo: str,
        rango_desde: datetime | None = None,
        rango_hasta: datetime | None = None,
    ) -> EjecucionTracking:
        ej = EjecucionTracking(
            modo=modo, parametros=parametros, version_algoritmo=version_algoritmo,
            rango_desde=rango_desde, rango_hasta=rango_hasta,
        )
        self._s.add(ej)
        await self._s.flush()
        return ej

    async def finalizar(
        self,
        ejecucion_id: int,
        estado: str,
        *,
        n_imagenes: int | None = None,
        n_celdas: int | None = None,
        n_tracks: int | None = None,
        mensaje: str | None = None,
    ) -> None:
        await self._s.execute(
            update(EjecucionTracking)
            .where(EjecucionTracking.id == ejecucion_id)
            .values(estado=estado, n_imagenes=n_imagenes, n_celdas=n_celdas,
                    n_tracks=n_tracks, mensaje=mensaje, finalizada_en=func.now())
        )

    async def obtener(self, ejecucion_id: int) -> EjecucionTracking | None:
        return await self._s.get(EjecucionTracking, ejecucion_id)

    async def borrar_las_que_solapan(self, desde: datetime, hasta: datetime) -> int:
        """
        Reproceso manual: borra las corridas cuyo rango se solapa con [desde, hasta).
        La cascada se lleva sus tracks, celdas y relaciones. Devuelve cuántas borró.
        """
        res = await self._s.execute(
            delete(EjecucionTracking)
            .where(
                EjecucionTracking.rango_desde < hasta,
                EjecucionTracking.rango_hasta > desde,
            )
            .returning(EjecucionTracking.id)
        )
        return len(res.all())


# ─────────────────────────────────────────────────────────────────────────────
# Celdas
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CeldaNueva:
    """Lo que el detector (F2) entrega por cada componente conexa."""

    imagen_id: int
    numero: int
    fecha_hora: datetime
    x_m: float               # centroide en EPSG:5344
    y_m: float
    poligono_wkt: str        # MULTIPOLYGON en EPSG:5344
    n_pixeles: int
    area_km2: float
    dbz_max: int
    dbz_medio: float
    area_nucleo_km2: float | None = None
    geo_corregida: bool = False


class CeldaTormentaRepository:
    """radar.celdas_tormenta: un eco en una imagen."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def crear_varias(self, ejecucion_id: int, celdas: list[CeldaNueva]) -> list[int]:
        """Inserta las celdas de una o más imágenes. Devuelve los ids en el mismo orden."""
        if not celdas:
            return []
        filas = [
            dict(
                imagen_id=c.imagen_id, ejecucion_id=ejecucion_id, numero=c.numero,
                fecha_hora=c.fecha_hora,
                centroide=func.ST_SetSRID(func.ST_MakePoint(c.x_m, c.y_m), SRID),
                poligono=func.ST_Multi(func.ST_GeomFromText(c.poligono_wkt, SRID)),
                n_pixeles=c.n_pixeles, area_km2=c.area_km2, area_nucleo_km2=c.area_nucleo_km2,
                dbz_max=c.dbz_max, dbz_medio=c.dbz_medio, geo_corregida=c.geo_corregida,
            )
            for c in celdas
        ]
        ids = []
        for f in filas:  # uno por uno: las expresiones PostGIS no van en executemany
            res = await self._s.execute(
                CeldaTormenta.__table__.insert().values(**f).returning(CeldaTormenta.id)
            )
            ids.append(res.scalar_one())
        return ids

    async def asignar_track(self, celda_ids: list[int], track_id: int | None) -> None:
        if celda_ids:
            await self._s.execute(
                update(CeldaTormenta).where(CeldaTormenta.id.in_(celda_ids)).values(track_id=track_id)
            )

    async def de_imagen(self, imagen_id: int, ejecucion_id: int | None = None) -> list[CeldaTormenta]:
        q = select(CeldaTormenta).where(CeldaTormenta.imagen_id == imagen_id)
        if ejecucion_id is not None:
            q = q.where(CeldaTormenta.ejecucion_id == ejecucion_id)
        return list((await self._s.execute(q.order_by(CeldaTormenta.numero))).scalars())

    async def de_track(self, track_id: int) -> list[CeldaTormenta]:
        q = select(CeldaTormenta).where(CeldaTormenta.track_id == track_id).order_by(CeldaTormenta.fecha_hora)
        return list((await self._s.execute(q)).scalars())

    async def recalcular_cinematica(self, track_id: int) -> None:
        """Distancia, velocidad, rumbo, Δt y Δárea de cada paso del track (LAG por fecha)."""
        await self._s.execute(
            text("""
                WITH p AS (
                    SELECT id, centroide, fecha_hora, area_km2,
                           LAG(centroide)  OVER w AS c0,
                           LAG(fecha_hora) OVER w AS t0,
                           LAG(area_km2)   OVER w AS a0
                    FROM radar.celdas_tormenta
                    WHERE track_id = :tid
                    WINDOW w AS (ORDER BY fecha_hora, id)
                )
                UPDATE radar.celdas_tormenta c SET
                    dt_min         = CASE WHEN p.c0 IS NULL THEN NULL
                                          ELSE EXTRACT(EPOCH FROM p.fecha_hora - p.t0) / 60 END,
                    distancia_m    = CASE WHEN p.c0 IS NULL THEN NULL ELSE ST_Distance(p.c0, p.centroide) END,
                    velocidad_kmh  = CASE WHEN p.c0 IS NULL OR p.fecha_hora = p.t0 THEN NULL
                                          ELSE ST_Distance(p.c0, p.centroide) / 1000.0
                                               / (EXTRACT(EPOCH FROM p.fecha_hora - p.t0) / 3600.0) END,
                    direccion_deg  = CASE WHEN p.c0 IS NULL OR ST_Equals(p.c0, p.centroide) THEN NULL
                                          ELSE degrees(ST_Azimuth(p.c0, p.centroide)) END,
                    delta_area_km2 = CASE WHEN p.c0 IS NULL THEN NULL ELSE p.area_km2 - p.a0 END
                FROM p WHERE c.id = p.id
            """),
            {"tid": track_id},
        )


# ─────────────────────────────────────────────────────────────────────────────
# Tracks
# ─────────────────────────────────────────────────────────────────────────────

class TrackTormentaRepository:
    """radar.tracks_tormenta: una tormenta con identidad propia."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def siguiente_codigo(self, fecha: datetime) -> str:
        """T-AAAAMMDD-NNN, consecutivo dentro del día de inicio."""
        prefijo = f"T-{fecha:%Y%m%d}-"
        res = await self._s.execute(
            select(func.max(TrackTormenta.codigo)).where(TrackTormenta.codigo.like(prefijo + "%"))
        )
        ultimo = res.scalar_one_or_none()
        n = int(ultimo.rsplit("-", 1)[1]) + 1 if ultimo else 1
        return f"{prefijo}{n:03d}"

    async def crear(self, ejecucion_id: int, inicio: datetime, codigo: str | None = None) -> TrackTormenta:
        tr = TrackTormenta(
            codigo=codigo or await self.siguiente_codigo(inicio),
            ejecucion_id=ejecucion_id, inicio=inicio, fin=inicio,
        )
        self._s.add(tr)
        await self._s.flush()
        return tr

    async def obtener(self, track_id: int) -> TrackTormenta | None:
        return await self._s.get(TrackTormenta, track_id)

    async def activos(self) -> list[TrackTormenta]:
        q = select(TrackTormenta).where(TrackTormenta.estado == "activo").order_by(TrackTormenta.id)
        return list((await self._s.execute(q)).scalars())

    async def cambiar_estado(self, track_id: int, estado: str) -> None:
        await self._s.execute(update(TrackTormenta).where(TrackTormenta.id == track_id).values(estado=estado))

    async def recalcular_totales(self, track_id: int) -> None:
        """Totales y trayectoria a partir de sus celdas (después de recalcular la cinemática)."""
        await self._s.execute(
            text("""
                WITH s AS (
                    SELECT min(fecha_hora) AS ini, max(fecha_hora) AS fin_, count(*) AS n,
                           ST_MakeLine(centroide ORDER BY fecha_hora, id) AS linea,
                           avg(velocidad_kmh) AS vmed, max(velocidad_kmh) AS vmax,
                           max(area_km2) AS amax, max(dbz_max) AS dmax,
                           avg(sin(radians(direccion_deg))) AS s_, avg(cos(radians(direccion_deg))) AS c_
                    FROM radar.celdas_tormenta WHERE track_id = :tid
                )
                UPDATE radar.tracks_tormenta t SET
                    inicio = s.ini, fin = s.fin_, n_celdas = s.n,
                    duracion_min = EXTRACT(EPOCH FROM s.fin_ - s.ini) / 60,
                    trayectoria = CASE WHEN s.n >= 2 THEN s.linea END,
                    distancia_total_km = CASE WHEN s.n >= 2 THEN ST_Length(s.linea) / 1000 END,
                    desplazamiento_neto_km = CASE WHEN s.n >= 2
                        THEN ST_Distance(ST_StartPoint(s.linea), ST_EndPoint(s.linea)) / 1000 END,
                    vel_media_kmh = s.vmed, vel_max_kmh = s.vmax,
                    direccion_media_deg = CASE WHEN s.s_ IS NULL THEN NULL
                        ELSE mod(degrees(atan2(s.s_, s.c_))::numeric + 360, 360)::real END,
                    area_max_km2 = s.amax, dbz_max = s.dmax, updated_at = now()
                FROM s WHERE t.id = :tid AND s.n > 0
            """),
            {"tid": track_id},
        )

    # ── Consultas para la API ────────────────────────────────────────────────

    @staticmethod
    def _filtro_rango(desde: datetime, hasta: datetime, estado: str | None):
        """Tracks que tienen actividad dentro de [desde, hasta)."""
        conds = [TrackTormenta.inicio < hasta, TrackTormenta.fin >= desde]
        if estado:
            conds.append(TrackTormenta.estado == estado)
        else:
            conds.append(TrackTormenta.estado != "espurio")
        return and_(*conds)

    async def contar(self, desde: datetime, hasta: datetime, estado: str | None = None) -> int:
        q = select(func.count()).select_from(TrackTormenta).where(self._filtro_rango(desde, hasta, estado))
        return (await self._s.execute(q)).scalar_one()

    async def listar(
        self, desde: datetime, hasta: datetime, estado: str | None = None,
        limit: int = 100, offset: int = 0,
    ) -> list[dict]:
        """Tracks del rango con su trayectoria en GeoJSON (EPSG:4326)."""
        q = (
            select(
                TrackTormenta,
                func.ST_AsGeoJSON(func.ST_Transform(TrackTormenta.trayectoria, 4326), 5).label("geo"),
            )
            .where(self._filtro_rango(desde, hasta, estado))
            .order_by(TrackTormenta.inicio, TrackTormenta.id)
            .limit(limit).offset(offset)
        )
        out = []
        for tr, geo in (await self._s.execute(q)).all():
            out.append({"track": tr, "trayectoria": json.loads(geo) if geo else None})
        return out

    async def trayectoria_geojson(self, track_id: int) -> dict | None:
        q = select(func.ST_AsGeoJSON(func.ST_Transform(TrackTormenta.trayectoria, 4326), 5)).where(
            TrackTormenta.id == track_id)
        geo = (await self._s.execute(q)).scalar_one_or_none()
        return json.loads(geo) if geo else None

    async def celdas_con_geojson(self, track_id: int) -> list[dict]:
        """Celdas del track en orden temporal, con el polígono en GeoJSON (EPSG:4326)."""
        q = (
            select(
                CeldaTormenta,
                func.ST_AsGeoJSON(func.ST_Transform(CeldaTormenta.poligono, 4326), 5).label("poly"),
            )
            .where(CeldaTormenta.track_id == track_id)
            .order_by(CeldaTormenta.fecha_hora, CeldaTormenta.id)
        )
        return [{"celda": c, "poligono": json.loads(p)} for c, p in (await self._s.execute(q)).all()]


# ─────────────────────────────────────────────────────────────────────────────
# Relaciones (grafo entre imágenes)
# ─────────────────────────────────────────────────────────────────────────────

class RelacionCeldasRepository:
    """radar.relaciones_celdas: aristas continuación / división / fusión."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def crear(self, origen_id: int, destino_id: int, tipo: str, metodo: str, score: float) -> None:
        if tipo not in TIPOS_RELACION:
            raise ValueError(f"tipo inválido: {tipo}")
        self._s.add(RelacionCeldas(
            celda_origen_id=origen_id, celda_destino_id=destino_id,
            tipo=tipo, metodo=metodo, score=score,
        ))
        await self._s.flush()

    async def padres(self, celda_id: int) -> list[RelacionCeldas]:
        q = select(RelacionCeldas).where(RelacionCeldas.celda_destino_id == celda_id)
        return list((await self._s.execute(q)).scalars())

    async def hijos(self, celda_id: int) -> list[RelacionCeldas]:
        q = select(RelacionCeldas).where(RelacionCeldas.celda_origen_id == celda_id)
        return list((await self._s.execute(q)).scalars())
