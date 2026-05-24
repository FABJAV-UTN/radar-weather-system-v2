# src/api/routers/imagenes.py
"""
Router de imágenes: listado, detalle y descarga de GeoTIFF.

Endpoints:
- GET  /imagenes              → Lista paginada
- GET  /imagenes/{id}         → Detalle de una imagen
- GET  /imagenes/{id}/geotiff → Descarga del GeoTIFF final
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_db
from src.api.schemas.imagen import ImagenDetalle, ImagenListaResponse, ImagenResumen
from src.db.repository import ImagenRadarRepository

router = APIRouter(prefix="/imagenes", tags=["imagenes"])


@router.get("", response_model=ImagenListaResponse)
async def listar_imagenes(
    estado: str | None = Query(default=None, description="Filtrar por estado"),
    origen: str | None = Query(default=None, description="Filtrar por origen ('local'|'url')"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> ImagenListaResponse:
    """
    Lista imágenes procesadas con filtros opcionales y paginación.

    - **estado**: pendiente | procesando | completado | error
    - **origen**: local | url
    """
    repo = ImagenRadarRepository(db)
    items = await repo.listar(estado=estado, origen=origen, limit=limit, offset=offset)
    return ImagenListaResponse(
        total=len(items),
        limit=limit,
        offset=offset,
        items=[ImagenResumen.model_validate(i) for i in items],
    )


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
    return ImagenDetalle.model_validate(imagen)


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