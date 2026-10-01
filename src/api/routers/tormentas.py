# src/api/routers/tormentas.py
"""
Router del tracking de tormentas (Subsistema 2). Solo lectura.

Endpoints:
- GET /tormentas/tracks?desde=&hasta=   → Tracks con actividad en el rango (fechas inclusivas)
- GET /tormentas/tracks/{id}            → Detalle de un track con sus celdas

Un rango sin tormentas devuelve 200 con items = [] (no es un error).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_db
from src.api.schemas.tormenta import CeldaResumen, TrackDetalle, TrackListaResponse, TrackResumen
from src.db.models_tracking import TrackTormenta
from src.db.repository_tracking import TrackTormentaRepository

router = APIRouter(prefix="/tormentas", tags=["tormentas"])

MAX_DIAS = 366
_ESTADOS = ("activo", "cerrado", "espurio")
_SIN_TABLAS = (
    "Las tablas del tracking no existen todavía en la base. "
    "Aplicá las migraciones: docker compose exec backend uv run --no-dev alembic upgrade head"
)


def _atributos(obj, modelo, geom: str) -> dict:
    """Columnas del ORM que pide el schema, sin la geometría cruda (WKB)."""
    return {k: getattr(obj, k) for k in modelo.model_fields if k != geom and hasattr(obj, k)}


def _resumen(track: TrackTormenta, trayectoria: dict | None) -> TrackResumen:
    return TrackResumen(**_atributos(track, TrackResumen, "trayectoria"), trayectoria=trayectoria)


@router.get("/tracks", response_model=TrackListaResponse)
async def listar_tracks(
    desde: date = Query(..., description="Primer día (AAAA-MM-DD), inclusive"),
    hasta: date = Query(..., description="Último día (AAAA-MM-DD), inclusive"),
    estado: str | None = Query(default=None, description="activo | cerrado | espurio"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> TrackListaResponse:
    """Tracks con actividad entre `desde` y `hasta`. Por defecto excluye los espurios."""
    if hasta < desde:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "'hasta' no puede ser anterior a 'desde'.")
    if (hasta - desde).days >= MAX_DIAS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"El rango máximo es de {MAX_DIAS} días.")
    if estado is not None and estado not in _ESTADOS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"estado debe ser uno de {_ESTADOS}.")

    t_desde = datetime.combine(desde, time.min)
    t_hasta = datetime.combine(hasta + timedelta(days=1), time.min)   # fin exclusivo
    repo = TrackTormentaRepository(db)
    try:
        total = await repo.contar(t_desde, t_hasta, estado)
        filas = await repo.listar(t_desde, t_hasta, estado, limit=limit, offset=offset)
        total_en_base = (await db.execute(
            select(func.count()).select_from(TrackTormenta).where(TrackTormenta.estado != "espurio")
        )).scalar_one()
    except ProgrammingError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _SIN_TABLAS)

    return TrackListaResponse(
        desde=desde, hasta=hasta, total=total, total_en_base=total_en_base,
        items=[_resumen(f["track"], f["trayectoria"]) for f in filas],
    )


@router.get("/tracks/{track_id}", response_model=TrackDetalle)
async def detalle_track(
    track_id: int,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> TrackDetalle:
    repo = TrackTormentaRepository(db)
    try:
        track = await repo.obtener(track_id)
        if track is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No existe el track {track_id}.")
        trayectoria = await repo.trayectoria_geojson(track_id)
        celdas = await repo.celdas_con_geojson(track_id)
    except ProgrammingError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _SIN_TABLAS)

    base = _resumen(track, trayectoria).model_dump()
    cel = [CeldaResumen(**_atributos(c["celda"], CeldaResumen, "poligono"), poligono=c["poligono"])
           for c in celdas]
    return TrackDetalle(**base, ejecucion_id=track.ejecucion_id, celdas=cel)
