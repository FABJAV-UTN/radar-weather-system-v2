# src/api/routers/procesamiento.py
"""
Router de procesamiento: ejecución del pipeline y consulta de métricas.

Endpoints:
- POST /procesamiento/url              → Ejecutar pipeline una vez desde URL DACC
- POST /procesamiento/local            → Ejecutar pipeline desde archivo local
- POST /procesamiento/upload           → Subir un archivo .gif/.png y procesarlo
- POST /procesamiento/carpeta          → Procesar lote desde carpeta del servidor
- POST /procesamiento/upload-lote      → Procesar lote via upload desde el cliente
- POST /procesamiento/lote/iniciar      → Resetear flag de cancelación (inicio de lote)
- POST /procesamiento/lote/cancelar    → Setear flag de cancelación del lote activo
- POST /procesamiento/scheduler/start  → Iniciar procesamiento continuo desde URL
- POST /procesamiento/scheduler/stop   → Detener procesamiento continuo
- GET  /procesamiento/scheduler/estado → Estado del scheduler
- GET  /procesamiento/{id}/metricas    → Consultar métricas de una imagen
- GET  /procesamiento/{id}/pasos       → Consultar pasos del pipeline
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_db
from src.api.schemas.imagen import (
    BatchPipelineResponse,
    PipelineResponse,
    ProcesarCarpetaRequest,
    ProcesarLocalRequest,
    ProcesarURLRequest,
)
from src.db.connection import AsyncSessionLocal
from src.db.repository import MetricaProcesamientoRepository, ProcesamentoPasoRepository
from src.subsistema1.orquestador import (
    PipelineCanceladoError,
    ejecutar_pipeline_local,
    ejecutar_pipeline_url,
)
from src.subsistema1 import scheduler

router = APIRouter(prefix="/procesamiento", tags=["procesamiento"])


# ── Flag de cancelación del lote activo ──────────────────────────────────────
# Se usa una variable de módulo (proceso único por worker de uvicorn).
# Se resetea al iniciar cada nuevo lote y se activa vía POST /lote/cancelar.

_lote_cancelado: bool = False


def _reset_cancelacion() -> None:
    global _lote_cancelado
    _lote_cancelado = False


def _lote_fue_cancelado() -> bool:
    return _lote_cancelado


async def _lote_debe_detenerse(http_request: Request) -> bool:
    return _lote_fue_cancelado() or await http_request.is_disconnected()


# ── Schemas del scheduler ─────────────────────────────────────────────────────

class SchedulerStartRequest(BaseModel):
    url: str | None = None
    intervalo_segundos: int = 120


# ── Endpoints de ejecución única ──────────────────────────────────────────────

@router.post("/url", response_model=PipelineResponse, status_code=status.HTTP_202_ACCEPTED)
async def procesar_desde_url(
    request: ProcesarURLRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> PipelineResponse:
    """
    Descarga la imagen desde la URL DACC y ejecuta el pipeline una vez.

    Si se omite `url`, usa la URL configurada en `.env` (`RADAR_URL`).
    """
    try:
        resultado = await ejecutar_pipeline_url(db, url=request.url, request=http_request)
    except PipelineCanceladoError:
        raise HTTPException(
            status_code=status.HTTP_499_CLIENT_CLOSED_REQUEST,
            detail="Procesamiento cancelado por el cliente.",
        )
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
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> PipelineResponse:
    """
    Lee el archivo desde `file_path` en el servidor y ejecuta el pipeline.
    """
    file_path = Path(request.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Archivo no encontrado en el servidor: {file_path}",
        )

    try:
        resultado = await ejecutar_pipeline_local(file_path, db, request=http_request)
    except PipelineCanceladoError:
        raise HTTPException(
            status_code=status.HTTP_499_CLIENT_CLOSED_REQUEST,
            detail="Procesamiento cancelado por el cliente.",
        )
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


def _respuesta_pipeline(resultado) -> PipelineResponse:
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


@router.post("/upload", response_model=PipelineResponse, status_code=status.HTTP_202_ACCEPTED)
async def procesar_upload_unico(
    http_request: Request,
    archivo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> PipelineResponse:
    """
    Sube un .gif/.png desde el cliente, lo procesa y elimina el temporal.
    """
    nombre = Path(archivo.filename or "").name
    if not (nombre.lower().endswith(".gif") or nombre.lower().endswith(".png")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se aceptan archivos .gif o .png.",
        )

    tmp_dir = tempfile.mkdtemp(prefix="radar_unico_")
    try:
        dest = Path(tmp_dir) / nombre
        with dest.open("wb") as f:
            shutil.copyfileobj(archivo.file, f)

        try:
            resultado = await ejecutar_pipeline_local(dest, db, request=http_request)
        except PipelineCanceladoError:
            raise HTTPException(
                status_code=status.HTTP_499_CLIENT_CLOSED_REQUEST,
                detail="Procesamiento cancelado por el cliente.",
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

        return _respuesta_pipeline(resultado)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/carpeta", response_model=BatchPipelineResponse, status_code=status.HTTP_200_OK)
async def procesar_carpeta(
    body: ProcesarCarpetaRequest,
    http_request: Request,
    _user: dict = Depends(get_current_user),
) -> BatchPipelineResponse:
    """Procesa todos los archivos .gif y .png de una carpeta del servidor."""
    folder_path = Path(body.folder_path)

    if not folder_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Carpeta no encontrada: {folder_path}")
    if not folder_path.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"La ruta no es una carpeta: {folder_path}")

    archivos = sorted(list(folder_path.glob("*.gif")) + list(folder_path.glob("*.png")))
    exitosos = 0
    fallidos = 0
    resultados = []
    cancelado = False

    for archivo in archivos:
        await asyncio.sleep(0)
        if await http_request.is_disconnected():
            cancelado = True
            break

        async with AsyncSessionLocal() as file_db:
            try:
                resultado = await ejecutar_pipeline_local(archivo, file_db, request=http_request)
                await file_db.commit()
                exitosos += 1
                m = resultado.metricas
                resultados.append({
                    "archivo": archivo.name, "imagen_id": resultado.imagen_id, "exito": True,
                    "pixeles_originales": m.pixeles_originales, "pixeles_limpios": m.pixeles_limpios,
                    "pixeles_rellenados": m.pixeles_rellenados, "pixeles_perdidos": m.pixeles_perdidos,
                    "error_relleno_pct": float(m.error_relleno_pct), "score_match": float(m.score_match),
                    "tiene_marco": m.tiene_marco, "mensaje_error": "",
                })
            except PipelineCanceladoError:
                await file_db.rollback()
                cancelado = True
                resultados.append({"archivo": archivo.name, "imagen_id": None, "exito": False, "mensaje_error": "Cancelado"})
                break
            except ValueError as e:
                await file_db.rollback()
                if await _lote_debe_detenerse(http_request):
                    cancelado = True
                    break
                fallidos += 1
                resultados.append({"archivo": archivo.name, "imagen_id": None, "exito": False, "mensaje_error": str(e)})
            except Exception as e:
                await file_db.rollback()
                if await _lote_debe_detenerse(http_request):
                    cancelado = True
                    break
                fallidos += 1
                resultados.append({"archivo": archivo.name, "imagen_id": None, "exito": False, "mensaje_error": f"{type(e).__name__}: {str(e)[:200]}"})

    return BatchPipelineResponse(total=len(archivos), exitosos=exitosos, fallidos=fallidos, resultados=resultados, cancelado=cancelado)


@router.post("/upload-lote", response_model=BatchPipelineResponse, status_code=status.HTTP_200_OK)
async def procesar_upload_lote(
    http_request: Request,
    archivos: list[UploadFile] = File(...),
    _user: dict = Depends(get_current_user),
) -> BatchPipelineResponse:
    """
    Recibe archivos .gif/.png desde el cliente, los procesa y limpia los temporales.

    La cancelación se detecta por dos vías (OR):
      1. `http_request.is_disconnected()` — el cliente cortó la conexión HTTP.
      2. `_lote_cancelado` — el cliente llamó a POST /procesamiento/lote/cancelar
         (necesario cuando el body ya fue recibido completo y is_disconnected no dispara).

    La flag se resetea solo con POST /procesamiento/lote/iniciar (una vez por sesión de lote).
    """
    tmp_dir = tempfile.mkdtemp(prefix="radar_lote_")
    try:
        paths = []
        for archivo in archivos:
            if not (archivo.filename.endswith(".gif") or archivo.filename.endswith(".png")):
                continue
            dest = Path(tmp_dir) / Path(archivo.filename).name
            with dest.open("wb") as f:
                shutil.copyfileobj(archivo.file, f)
            paths.append(dest)

        paths = sorted(paths)
        exitosos = 0
        fallidos = 0
        resultados = []
        cancelado = False

        for path in paths:
            await asyncio.sleep(0)

            if await _lote_debe_detenerse(http_request):
                cancelado = True
                break

            async with AsyncSessionLocal() as file_db:
                try:
                    resultado = await ejecutar_pipeline_local(path, file_db, request=http_request)
                    await file_db.commit()
                    exitosos += 1
                    m = resultado.metricas
                    resultados.append({
                        "archivo": path.name, "imagen_id": resultado.imagen_id, "exito": True,
                        "pixeles_originales": m.pixeles_originales, "pixeles_limpios": m.pixeles_limpios,
                        "pixeles_rellenados": m.pixeles_rellenados, "pixeles_perdidos": m.pixeles_perdidos,
                        "error_relleno_pct": float(m.error_relleno_pct), "score_match": float(m.score_match),
                        "tiene_marco": m.tiene_marco, "mensaje_error": "",
                    })
                except PipelineCanceladoError:
                    await file_db.rollback()
                    cancelado = True
                    break
                except ValueError as e:
                    await file_db.rollback()
                    if await _lote_debe_detenerse(http_request):
                        cancelado = True
                        break
                    fallidos += 1
                    resultados.append({
                        "archivo": path.name, "imagen_id": None, "exito": False,
                        "mensaje_error": str(e)[:200],
                    })
                except Exception as e:
                    await file_db.rollback()
                    if await _lote_debe_detenerse(http_request):
                        cancelado = True
                        break
                    fallidos += 1
                    resultados.append({
                        "archivo": path.name, "imagen_id": None, "exito": False,
                        "mensaje_error": f"{type(e).__name__}: {str(e)[:200]}",
                    })

        return BatchPipelineResponse(total=len(paths), exitosos=exitosos, fallidos=fallidos, resultados=resultados, cancelado=cancelado)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Endpoint de cancelación del lote activo ───────────────────────────────────

@router.post("/lote/iniciar", dependencies=[Depends(get_current_user)])
async def iniciar_lote() -> dict:
    """
    Resetea la flag de cancelación al comenzar un lote nuevo.

    Debe llamarse una sola vez antes de la primera tanda de upload-lote.
    """
    _reset_cancelacion()
    return {"mensaje": "Lote iniciado. Flag de cancelación reseteada."}


@router.post("/lote/cancelar", dependencies=[Depends(get_current_user)])
async def cancelar_lote() -> dict:
    """
    Señala al loop de upload-lote que debe detenerse en la próxima iteración.

    El frontend lo llama cuando el usuario hace clic en "Cancelar", en paralelo
    al abort del fetch (AbortController). Esto cubre el caso en que el body
    ya fue recibido completo y `is_disconnected()` no llega a dispararse.
    """
    global _lote_cancelado
    _lote_cancelado = True
    return {"mensaje": "Señal de cancelación recibida. El lote se detendrá en el próximo archivo."}


# ── Endpoints del scheduler (procesamiento continuo) ─────────────────────────

@router.post("/scheduler/start", dependencies=[Depends(get_current_user)])
async def iniciar_scheduler(body: SchedulerStartRequest) -> dict:
    """
    Inicia el procesamiento continuo desde la URL DACC.

    Descarga y procesa cada `intervalo_segundos` (default: 120).
    Si falla por cualquier motivo, igual espera y reintenta.
    """
    iniciado = scheduler.start(url=body.url, intervalo_segundos=body.intervalo_segundos)
    if not iniciado:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El scheduler ya está activo.",
        )
    return {"mensaje": "Scheduler iniciado", **scheduler.get_estado()}


@router.post("/scheduler/stop", dependencies=[Depends(get_current_user)])
async def detener_scheduler() -> dict:
    """Detiene el procesamiento continuo."""
    detenido = scheduler.stop()
    if not detenido:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El scheduler no estaba activo.",
        )
    return {"mensaje": "Scheduler detenido", **scheduler.get_estado()}


@router.get("/scheduler/estado", dependencies=[Depends(get_current_user)])
async def estado_scheduler() -> dict:
    """Devuelve el estado actual del scheduler (activo, último resultado, contadores)."""
    return scheduler.get_estado()


# ── Endpoints de métricas y pasos ─────────────────────────────────────────────

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Métricas no encontradas.")
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
        {"id": p.id, "paso": p.paso, "exitoso": p.exitoso, "mensaje_error": p.mensaje_error, "ejecutado_en": p.ejecutado_en}
        for p in pasos
    ]
