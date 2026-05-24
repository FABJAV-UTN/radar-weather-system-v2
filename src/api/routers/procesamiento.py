# src/api/routers/procesamiento.py
"""
Router de procesamiento: ejecución del pipeline y consulta de métricas.

Endpoints:
- POST /procesamiento/url              → Pipeline desde URL DACC (una vez)
- POST /procesamiento/url/loop/iniciar → Inicia descarga periódica automática
- POST /procesamiento/url/loop/detener → Detiene la descarga periódica
- GET  /procesamiento/url/loop/estado  → Estado del loop (activo/inactivo)
- POST /procesamiento/local            → Pipeline desde un archivo local
- POST /procesamiento/lote             → Pipeline para todos los GIF de una carpeta
- GET  /procesamiento/{id}/metricas    → Métricas de una imagen
- GET  /procesamiento/{id}/pasos       → Pasos del pipeline de una imagen
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.dependencies import get_current_user, get_db
from src.api.schemas.imagen import PipelineResponse, ProcesarLocalRequest, ProcesarURLRequest
from src.config import settings
from src.db.repository import MetricaProcesamientoRepository, ProcesamentoPasoRepository
from src.subsistema1.orquestador import ejecutar_pipeline_local, ejecutar_pipeline_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/procesamiento", tags=["procesamiento"])


# ── Estado del loop de descarga periódica ─────────────────────────────────────

class _LoopState:
    """Singleton que mantiene el estado del loop de descarga periódica."""
    activo: bool = False
    tarea: asyncio.Task | None = None
    ciclos_completados: int = 0
    ciclos_exitosos: int = 0
    ultimo_error: str = ""
    intervalo_minutos: int = 2
    url: str | None = None


_loop_state = _LoopState()


async def _loop_descarga(url: str | None, intervalo_minutos: int) -> None:
    """Tarea de background que descarga y procesa en loop hasta que se detiene."""
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    logger.info("Loop de descarga iniciado — intervalo=%d min", intervalo_minutos)

    while _loop_state.activo:
        _loop_state.ciclos_completados += 1
        logger.info("Loop ciclo %d — descargando...", _loop_state.ciclos_completados)

        async with AsyncSessionLocal() as session:
            try:
                resultado = await ejecutar_pipeline_url(session, url=url)
                await session.commit()
                if resultado.exito:
                    _loop_state.ciclos_exitosos += 1
                    _loop_state.ultimo_error = ""
                    logger.info(
                        "Loop ciclo %d OK — imagen_id=%d, score=%.4f",
                        _loop_state.ciclos_completados,
                        resultado.imagen_id,
                        resultado.metricas.score_match,
                    )
                else:
                    _loop_state.ultimo_error = resultado.mensaje_error
                    logger.warning("Loop ciclo %d FALLO — %s", _loop_state.ciclos_completados, resultado.mensaje_error)
            except ValueError as e:
                await session.rollback()
                _loop_state.ultimo_error = str(e)
                logger.info("Loop ciclo %d saltado (duplicado) — %s", _loop_state.ciclos_completados, e)
            except Exception as e:
                await session.rollback()
                _loop_state.ultimo_error = str(e)
                logger.error("Loop ciclo %d error — %s", _loop_state.ciclos_completados, e)

        # Esperar el intervalo (en chunks de 1s para poder detener rápido)
        for _ in range(intervalo_minutos * 60):
            if not _loop_state.activo:
                break
            await asyncio.sleep(1)

    await engine.dispose()
    logger.info("Loop de descarga detenido.")


# ── Schemas adicionales ───────────────────────────────────────────────────────

class IniciarLoopRequest(BaseModel):
    intervalo_minutos: int = Field(default=2, ge=1, le=60, description="Intervalo entre descargas (minutos)")
    url: str | None = Field(default=None, description="URL alternativa. Si se omite, usa RADAR_URL del .env")


class LoopEstadoResponse(BaseModel):
    activo: bool
    ciclos_completados: int
    ciclos_exitosos: int
    intervalo_minutos: int
    ultimo_error: str
    url: str | None


class ProcesarLoteRequest(BaseModel):
    carpeta: str = Field(..., description="Ruta absoluta a la carpeta con archivos GIF/PNG")
    patron: str = Field(default="*.gif", description="Patrón glob (ej: '*.gif', '*.png', '*.gif *.png')")


class LoteResponse(BaseModel):
    total: int
    exitosos: int
    fallidos: int
    saltados: int
    resultados: list[dict]


# ── Endpoints: pipeline una sola vez ─────────────────────────────────────────

@router.post("/url", response_model=PipelineResponse, status_code=status.HTTP_202_ACCEPTED)
async def procesar_desde_url(
    request: ProcesarURLRequest,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> PipelineResponse:
    """
    Descarga la imagen desde la URL DACC y ejecuta el pipeline completo (una sola vez).

    Si se omite `url`, usa la URL configurada en `.env` (`RADAR_URL`).
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
            detail=f"Archivo no encontrado: {file_path}",
        )
    if file_path.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{file_path}' es una carpeta. Usá /procesamiento/lote para procesar carpetas.",
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


# ── Endpoint: lote ────────────────────────────────────────────────────────────

@router.post("/lote", response_model=LoteResponse, status_code=status.HTTP_200_OK)
async def procesar_lote(
    request: ProcesarLoteRequest,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> LoteResponse:
    """
    Procesa todos los archivos GIF/PNG de una carpeta en orden.

    - `carpeta`: ruta absoluta en el servidor (ej: `/home/fabio/Descargas/radar/`)
    - `patron`: patrón glob, por defecto `*.gif`

    Devuelve un resumen con exitosos, fallidos y saltados (duplicados).
    """
    carpeta = Path(request.carpeta)
    if not carpeta.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Carpeta no encontrada: {carpeta}")
    if not carpeta.is_dir():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"'{carpeta}' no es una carpeta.")

    archivos = sorted(carpeta.glob(request.patron))
    if not archivos:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontraron archivos con patrón '{request.patron}' en {carpeta}",
        )

    resultados = []
    exitosos = 0
    fallidos = 0
    saltados = 0

    # Crear engine propio para el lote (sesión por archivo)
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    for archivo in archivos:
        async with AsyncSessionLocal() as session:
            try:
                resultado = await ejecutar_pipeline_local(archivo, session)
                await session.commit()
                if resultado.exito:
                    exitosos += 1
                    resultados.append({
                        "archivo": archivo.name,
                        "estado": "ok",
                        "imagen_id": resultado.imagen_id,
                        "score_match": resultado.metricas.score_match,
                        "error": "",
                    })
                else:
                    fallidos += 1
                    resultados.append({
                        "archivo": archivo.name,
                        "estado": "error",
                        "imagen_id": resultado.imagen_id,
                        "score_match": 0.0,
                        "error": resultado.mensaje_error,
                    })
            except ValueError as e:
                await session.rollback()
                saltados += 1
                resultados.append({
                    "archivo": archivo.name,
                    "estado": "saltado",
                    "imagen_id": None,
                    "score_match": 0.0,
                    "error": str(e),
                })
            except Exception as e:
                await session.rollback()
                fallidos += 1
                resultados.append({
                    "archivo": archivo.name,
                    "estado": "error",
                    "imagen_id": None,
                    "score_match": 0.0,
                    "error": str(e),
                })

    await engine.dispose()

    return LoteResponse(
        total=len(archivos),
        exitosos=exitosos,
        fallidos=fallidos,
        saltados=saltados,
        resultados=resultados,
    )


# ── Endpoints: loop periódico desde URL ───────────────────────────────────────

@router.post("/url/loop/iniciar", status_code=status.HTTP_200_OK)
async def iniciar_loop(
    request: IniciarLoopRequest,
    background_tasks: BackgroundTasks,
    _user: dict = Depends(get_current_user),
) -> dict:
    """
    Inicia la descarga periódica automática desde la URL DACC.

    - `intervalo_minutos`: cada cuántos minutos descarga (default: 2, máx: 60)
    - `url`: URL alternativa (opcional)

    Solo puede haber un loop activo a la vez. Para cambiar parámetros,
    detené el loop y volvé a iniciarlo.
    """
    if _loop_state.activo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El loop ya está activo. Detené el loop actual antes de iniciar uno nuevo.",
        )

    _loop_state.activo = True
    _loop_state.ciclos_completados = 0
    _loop_state.ciclos_exitosos = 0
    _loop_state.ultimo_error = ""
    _loop_state.intervalo_minutos = request.intervalo_minutos
    _loop_state.url = request.url

    background_tasks.add_task(_loop_descarga, request.url, request.intervalo_minutos)

    return {
        "mensaje": f"Loop iniciado. Descargando cada {request.intervalo_minutos} minuto(s).",
        "url": request.url or settings.radar_url,
        "intervalo_minutos": request.intervalo_minutos,
    }


@router.post("/url/loop/detener", status_code=status.HTTP_200_OK)
async def detener_loop(
    _user: dict = Depends(get_current_user),
) -> dict:
    """
    Detiene la descarga periódica. El ciclo actual termina antes de parar.
    """
    if not _loop_state.activo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El loop no está activo.",
        )

    _loop_state.activo = False
    return {
        "mensaje": "Loop detenido. El ciclo actual terminará en unos segundos.",
        "ciclos_completados": _loop_state.ciclos_completados,
        "ciclos_exitosos": _loop_state.ciclos_exitosos,
    }


@router.get("/url/loop/estado", response_model=LoopEstadoResponse)
async def estado_loop(
    _user: dict = Depends(get_current_user),
) -> LoopEstadoResponse:
    """
    Devuelve el estado actual del loop de descarga periódica.
    """
    return LoopEstadoResponse(
        activo=_loop_state.activo,
        ciclos_completados=_loop_state.ciclos_completados,
        ciclos_exitosos=_loop_state.ciclos_exitosos,
        intervalo_minutos=_loop_state.intervalo_minutos,
        ultimo_error=_loop_state.ultimo_error,
        url=_loop_state.url,
    )


# ── Endpoints: métricas y pasos ───────────────────────────────────────────────

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