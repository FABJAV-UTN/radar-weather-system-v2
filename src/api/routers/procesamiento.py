
# src/api/routers/procesamiento.py
"""
Router de procesamiento: ejecución del pipeline y consulta de métricas.

Endpoints:
- POST /procesamiento/url          → Ejecutar pipeline desde URL DACC
- POST /procesamiento/local        → Ejecutar pipeline desde archivo local
- GET  /procesamiento/{id}/metricas → Consultar métricas de una imagen
- GET  /procesamiento/{id}/pasos   → Consultar pasos del pipeline
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_db
from src.api.schemas.imagen import PipelineResponse, ProcesarLocalRequest, ProcesarURLRequest
from src.db.repository import MetricaProcesamientoRepository, ProcesamentoPasoRepository
from src.subsistema1.orquestador import ejecutar_pipeline_local, ejecutar_pipeline_url

router = APIRouter(prefix="/procesamiento", tags=["procesamiento"])


@router.post("/url", response_model=PipelineResponse, status_code=status.HTTP_202_ACCEPTED)
async def procesar_desde_url(
    request: ProcesarURLRequest,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> PipelineResponse:
    """
    Descarga la imagen desde la URL DACC y ejecuta el pipeline completo.

    Si se omite `url`, usa la URL configurada en `.env` (`RADAR_URL`).
    Devuelve el ID de la imagen creada y las métricas del pipeline.
    """
    try:
        resultado = await ejecutar_pipeline_url(db, url=request.url)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    m = resultado.metricas
    return PipelineResponse(
        imagen_id=resultado.imagen_id,
        exito=resultado.exito,
        mensaje_error=resultado.mensaje_error,
        pixeles_originales=m.pixeles_originales,
        pixeles_limpios=m.pixeles_limpios,
        pixeles_rellenados=m.pixeles_rellenados,
        pixeles_perdidos=m.pixeles_perdidos,
        error_relleno_pct=m.error_relleno_pct,
        score_match=m.score_match,
        tiene_marco=m.tiene_marco,
    )


@router.post("/local", response_model=PipelineResponse, status_code=status.HTTP_202_ACCEPTED)
async def procesar_desde_local(
    request: ProcesarLocalRequest,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> PipelineResponse:
    """
    Lee el archivo desde `file_path` en el servidor y ejecuta el pipeline.

    El archivo debe ser un PNG o GIF con nombre en formato `radar_YYYYMMDD_HHMMSS.gif`.
    """
    file_path = Path(request.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Archivo no encontrado en el servidor: {file_path}",
        )

    try:
        resultado = await ejecutar_pipeline_local(file_path, db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    m = resultado.metricas
    return PipelineResponse(
        imagen_id=resultado.imagen_id,
        exito=resultado.exito,
        mensaje_error=resultado.mensaje_error,
        pixeles_originales=m.pixeles_originales,
        pixeles_limpios=m.pixeles_limpios,
        pixeles_rellenados=m.pixeles_rellenados,
        pixeles_perdidos=m.pixeles_perdidos,
        error_relleno_pct=m.error_relleno_pct,
        score_match=m.score_match,
        tiene_marco=m.tiene_marco,
    )


@router.get("/{imagen_id}/metricas")
async def obtener_metricas(
    imagen_id: int,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> dict:
    """Devuelve las métricas de calidad del pipeline para una imagen."""
    repo = MetricaProcesamientoRepository(db)
    metrica = await repo.obtener_por_imagen(imagen_id)
    if metrica is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Métricas no encontradas para esta imagen.",
        )
    return {
        "imagen_id": imagen_id,
        "pixeles_originales": metrica.pixeles_originales,
        "pixeles_limpios": metrica.pixeles_limpios,
        "pixeles_rellenados": metrica.pixeles_rellenados,
        "pixeles_perdidos": metrica.pixeles_perdidos,
        "error_relleno_pct": float(metrica.error_relleno_pct),
        "procesado_en": metrica.procesado_en,
    }


@router.get("/{imagen_id}/pasos")
async def obtener_pasos(
    imagen_id: int,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> list[dict]:
    """Devuelve el historial de pasos del pipeline para una imagen."""
    repo = ProcesamentoPasoRepository(db)
    pasos = await repo.listar_por_imagen(imagen_id)
    return [
        {
            "id": p.id,
            "paso": p.paso,
            "exitoso": p.exitoso,
            "mensaje_error": p.mensaje_error,
            "ejecutado_en": p.ejecutado_en,
        }
        for p in pasos
    ]
