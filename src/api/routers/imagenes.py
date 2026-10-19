# src/api/routers/imagenes.py
"""
Router de imágenes: listado, detalle y descarga de GeoTIFF.

Endpoints:
- GET  /imagenes                              → Lista paginada con sort server-side
- GET  /imagenes/serie?desde=&hasta=          → Cuadros del carrusel (id + hora) de un rango
- GET  /imagenes/descargar-lote?desde=&hasta= → ZIP con GeoTIFFs de un rango de fecha y hora
- GET  /imagenes/{id}                         → Detalle de una imagen
- GET  /imagenes/{id}/geotiff                 → Descarga del GeoTIFF final (1 banda dBZ)
- GET  /imagenes/{id}/vista                   → PNG en gris con el dBZ de cada píxel (carrusel)
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_db
from src.api.schemas.imagen import (
    FrameSerie,
    ImagenDetalle,
    ImagenListaResponse,
    ImagenResumen,
    SerieResponse,
)
from src.api.vista_dbz import geotiff_a_vista
from src.db.models import MetricaProcesamiento
from src.db.repository import ImagenRadarRepository

router = APIRouter(prefix="/imagenes", tags=["imagenes"])

# Valores válidos de sort_by aceptados por el endpoint
_SORT_BY_VALUES = Literal["id", "fecha", "origen", "estado", "dbz"]
_SORT_DIR_VALUES = Literal["asc", "desc"]

# Tope de cuadros por pedido del carrusel (~2,7 días del scheduler a 2 min).
MAX_FRAMES_SERIE = 2000


def _validar_rango(desde: datetime, hasta: datetime) -> None:
    if hasta < desde:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'hasta' es anterior a 'desde'.",
        )


# ── Listado paginado ───────────────────────────────────────────────────────────

@router.get("", response_model=ImagenListaResponse)
async def listar_imagenes(
    estado: str | None = Query(default=None, description="Filtrar por estado"),
    origen: str | None = Query(default=None, description="Filtrar por origen ('local'|'url')"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort_by: _SORT_BY_VALUES = Query(
        default="fecha",
        description="Columna de ordenamiento: id | fecha | origen | estado | dbz",
    ),
    sort_dir: _SORT_DIR_VALUES = Query(
        default="desc",
        description="Dirección: asc | desc",
    ),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> ImagenListaResponse:
    """
    Lista imágenes procesadas con filtros opcionales, paginación y ordenamiento
    completamente resuelto en la base de datos (no en el cliente).

    - **estado**: pendiente | procesando | completado | error
    - **origen**: local | url
    - **sort_by**: id | fecha | origen | estado | dbz
    - **sort_dir**: asc | desc

    Devuelve `total` con el conteo real (sin limit/offset) para calcular páginas.
    """
    repo = ImagenRadarRepository(db)
    total = await repo.contar(estado=estado, origen=origen)
    items = await repo.listar(
        estado=estado,
        origen=origen,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )

    # Cargar dbz_max para las imágenes de esta página con un JOIN eficiente
    imagen_ids = [img.id for img in items]
    dbz_map: dict[int, float | None] = {}
    if imagen_ids:
        result = await db.execute(
            select(MetricaProcesamiento.imagen_id, MetricaProcesamiento.dbz_max).where(
                MetricaProcesamiento.imagen_id.in_(imagen_ids)
            )
        )
        for row in result.all():
            dbz_map[row.imagen_id] = row.dbz_max

    # Construir items con dbz_max inyectado
    items_response = []
    for img in items:
        resumen = ImagenResumen.model_validate(img)
        resumen.dbz_max = dbz_map.get(img.id)
        items_response.append(resumen)

    return ImagenListaResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=items_response,
    )


# ── Descarga masiva como ZIP ───────────────────────────────────────────────────
# IMPORTANTE: esta ruta debe ir ANTES de /{imagen_id} para que FastAPI no
# intente parsear "descargar-lote" como un int.

@router.get("/serie", response_model=SerieResponse)
async def serie_imagenes(
    desde: datetime = Query(..., description="Inicio (AAAA-MM-DDTHH:MM, hora argentina, inclusive)"),
    hasta: datetime = Query(..., description="Fin (AAAA-MM-DDTHH:MM, hora argentina, inclusive)"),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> SerieResponse:
    """
    Cuadros del carrusel: imágenes completadas del rango en orden cronológico.

    Devuelve solo id y hora; cada cuadro se pide después con /{id}/vista.
    Si el rango supera MAX_FRAMES_SERIE imágenes, se devuelven las primeras y
    `truncada` es True.
    """
    _validar_rango(desde, hasta)
    filas = await ImagenRadarRepository(db).listar_serie(desde, hasta, MAX_FRAMES_SERIE + 1)
    return SerieResponse(
        items=[FrameSerie(id=i, fecha_hora=f) for i, f in filas[:MAX_FRAMES_SERIE]],
        truncada=len(filas) > MAX_FRAMES_SERIE,
    )


@router.get("/descargar-lote")
async def descargar_lote(
    desde: datetime = Query(..., description="Inicio (AAAA-MM-DDTHH:MM, hora argentina, inclusive)"),
    hasta: datetime = Query(..., description="Fin (AAAA-MM-DDTHH:MM, hora argentina, inclusive)"),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """
    Descarga un ZIP con todos los GeoTIFFs completados en el rango [desde, hasta].

    El ZIP se arma en memoria; cada archivo se llama `radar_<id>_<fecha_hora>.tif`.
    Si no hay imágenes completadas en el rango, devuelve 404.

    Nota: Los GeoTIFFs tienen 1 banda dBZ (uint8), NoData=0, completos (sin filtrar niveles).
    """
    _validar_rango(desde, hasta)
    geotiffs = await ImagenRadarRepository(db).listar_geotiffs_por_rango(desde, hasta)
    if not geotiffs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No hay imágenes completadas entre {desde:%Y-%m-%d %H:%M} y {hasta:%Y-%m-%d %H:%M}.",
        )

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for imagen_id, fecha_hora, geotiff_data in geotiffs:
            zf.writestr(f"radar_{imagen_id}_{fecha_hora:%Y%m%d_%H%M%S}.tif", geotiff_data)
    zip_buffer.seek(0)

    zip_filename = f"radar_{desde:%Y%m%d_%H%M}_{hasta:%Y%m%d_%H%M}.zip"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )


# ── Detalle ────────────────────────────────────────────────────────────────────

@router.get("/{imagen_id}", response_model=ImagenDetalle)
async def obtener_imagen(
    imagen_id: int,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> ImagenDetalle:
    """Devuelve el detalle de una imagen por su ID."""
    repo = ImagenRadarRepository(db)
    imagen = await repo.obtener_por_id(imagen_id)
    if imagen is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imagen no encontrada.")

    detalle = ImagenDetalle.model_validate(imagen)

    # Inyectar dbz_max desde metricas
    result = await db.execute(
        select(MetricaProcesamiento.dbz_max).where(
            MetricaProcesamiento.imagen_id == imagen_id
        )
    )
    row = result.scalar_one_or_none()
    detalle.dbz_max = row

    return detalle


# ── Descarga individual ────────────────────────────────────────────────────────

@router.get(
    "/{imagen_id}/geotiff",
    response_class=Response,
    responses={
        200: {
            "content": {"image/tiff": {}},
            "description": "GeoTIFF con 1 banda dBZ (uint8). NoData=0. Puede abrirse en QGIS/ArcGIS/rasterio.",
        },
        404: {"description": "Imagen no encontrada o GeoTIFF no disponible."},
    },
)
async def descargar_geotiff(
    imagen_id: int,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> Response:
    """
    Descarga el GeoTIFF corregido de una imagen completada.

    El archivo tiene:
    - **1 banda** con valores dBZ (uint8): 0=NoData, 10-80=niveles de precipitación
    - CRS y Transform geoespacial para ubicación exacta
    - Compresión LZW

    El archivo se llama `radar_<id>_<fecha_hora>.tif`.
    Puede abrirse directamente en QGIS, ArcGIS o rasterio.
    Al pasar el mouse sobre un píxel en QGIS, mostrará el valor dBZ.
    """
    repo = ImagenRadarRepository(db)
    imagen = await repo.obtener_por_id(imagen_id)
    if imagen is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imagen no encontrada.")
    if not imagen.geotiff_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GeoTIFF no disponible. La imagen puede estar pendiente o haber fallado.",
        )

    filename = f"radar_{imagen_id}_{imagen.fecha_hora.strftime('%Y%m%d_%H%M%S')}.tif"
    return Response(
        content=imagen.geotiff_data,
        media_type="image/tiff",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Vista para el carrusel ─────────────────────────────────────────────────────

@router.get(
    "/{imagen_id}/vista",
    response_class=Response,
    responses={
        200: {
            "content": {"image/png": {}},
            "description": (
                "PNG en gris (8 bits): el valor de cada píxel es el dBZ (0 = sin dato). "
                "Header X-Limites: oeste,sur,este,norte en grados (para el mapa)."
            ),
        },
        404: {"description": "Imagen no encontrada o GeoTIFF no disponible."},
    },
)
async def vista_dbz(
    imagen_id: int,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> Response:
    """
    Banda dBZ del GeoTIFF como PNG sin pérdida, para que el frontend la
    coloree con la paleta del radar. Los límites geográficos del cuadro van
    en el header X-Limites, para apoyarlo sobre el mapa.
    """
    geotiff = await ImagenRadarRepository(db).obtener_geotiff(imagen_id)
    if not geotiff:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GeoTIFF no disponible para esta imagen.",
        )
    vista = geotiff_a_vista(geotiff)
    # Sin caché HTTP: el contenido cambia si la imagen se reprocesa.
    # El carrusel ya guarda los cuadros en memoria mientras está abierto.
    headers = {"Cache-Control": "no-store"}
    if vista.limites is not None:
        headers["X-Limites"] = ",".join(str(v) for v in vista.limites)
    return Response(content=vista.png, media_type="image/png", headers=headers)
