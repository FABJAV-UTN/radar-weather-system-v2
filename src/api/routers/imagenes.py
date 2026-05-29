# src/api/routers/imagenes.py
"""
Router de imágenes: listado, detalle y descarga de GeoTIFF.

Endpoints:
- GET  /imagenes                              → Lista paginada con sort server-side
- GET  /imagenes/descargar-lote?desde=&hasta= → ZIP con GeoTIFFs de un rango de fechas
- GET  /imagenes/{id}                         → Detalle de una imagen
- GET  /imagenes/{id}/geotiff                 → Descarga del GeoTIFF final
"""
from __future__ import annotations

import io
import zipfile
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_db
from src.api.schemas.imagen import ImagenDetalle, ImagenListaResponse, ImagenResumen
from src.db.models import ImagenRadar, MetricaProcesamiento
from src.db.repository import ImagenRadarRepository

router = APIRouter(prefix="/imagenes", tags=["imagenes"])

# Valores válidos de sort_by aceptados por el endpoint
_SORT_BY_VALUES = Literal["id", "fecha", "origen", "estado", "dbz"]
_SORT_DIR_VALUES = Literal["asc", "desc"]


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

@router.get("/descargar-lote")
async def descargar_lote(
    desde: date = Query(..., description="Fecha de inicio (YYYY-MM-DD, inclusive)"),
    hasta: date = Query(..., description="Fecha de fin (YYYY-MM-DD, inclusive)"),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """
    Descarga un ZIP con todos los GeoTIFFs completados en el rango [desde, hasta].

    El ZIP se arma en memoria; cada archivo se llama `radar_<id>_<fecha_hora>.tif`.
    Si no hay imágenes completadas en el rango, devuelve 404.
    """
    repo = ImagenRadarRepository(db)
    imagenes = await repo.listar_por_rango(
        desde=datetime(desde.year, desde.month, desde.day, 0, 0, 0),
        hasta=datetime(hasta.year, hasta.month, hasta.day, 23, 59, 59),
    )

    completadas = [img for img in imagenes if img.estado == "completado" and img.geotiff_data]
    if not completadas:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No hay imágenes completadas entre {desde} y {hasta}.",
        )

    # Armar ZIP en memoria
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for img in completadas:
            filename = f"radar_{img.id}_{img.fecha_hora.strftime('%Y%m%d_%H%M%S')}.tif"
            zf.writestr(filename, img.geotiff_data)
    zip_buffer.seek(0)

    zip_filename = f"radar_{desde.strftime('%Y%m%d')}_{hasta.strftime('%Y%m%d')}.zip"
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
            "description": "GeoTIFF corregido listo para descargar.",
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

    El archivo se llama `radar_<id>_<fecha_hora>.tif`.
    Puede abrirse directamente en QGIS, ArcGIS o rasterio.
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
