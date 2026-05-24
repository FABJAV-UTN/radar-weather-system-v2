# src/api/routers/procesamiento.py
"""
Router de procesamiento: ejecución del pipeline y consulta de métricas.

Endpoints:
- POST /procesamiento/url          → Ejecutar pipeline desde URL DACC
- POST /procesamiento/local        → Ejecutar pipeline desde archivo local
- POST /procesamiento/carpeta      → Procesar lote de archivos en carpeta (ruta servidor)
- POST /procesamiento/upload-lote  → Procesar lote via upload desde el cliente
- GET  /procesamiento/{id}/metricas → Consultar métricas de una imagen
- GET  /procesamiento/{id}/pasos   → Consultar pasos del pipeline
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
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

router = APIRouter(prefix="/procesamiento", tags=["procesamiento"])


@router.post("/url", response_model=PipelineResponse, status_code=status.HTTP_202_ACCEPTED)
async def procesar_desde_url(
    request: ProcesarURLRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> PipelineResponse:
    """
    Descarga la imagen desde la URL DACC y ejecuta el pipeline completo.

    Si se omite `url`, usa la URL configurada en `.env` (`RADAR_URL`).
    Devuelve el ID de la imagen creada y las métricas del pipeline.

    **Cancelable:** Si cerrás la pestaña o hacés "Cancel" en Swagger,
    el pipeline se detiene inmediatamente.
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

    El archivo debe ser un PNG o GIF con nombre en formato `radar_YYYYMMDD_HHMMSS.gif`.

    **Cancelable:** Si cerrás la pestaña o hacés "Cancel" en Swagger,
    el pipeline se detiene inmediatamente.
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


@router.post("/carpeta", response_model=BatchPipelineResponse, status_code=status.HTTP_200_OK)
async def procesar_carpeta(
    body: ProcesarCarpetaRequest,
    http_request: Request,
    _user: dict = Depends(get_current_user),
) -> BatchPipelineResponse:
    """
    Procesa todos los archivos .gif y .png de una carpeta del servidor secuencialmente.

    Cada archivo usa su propia sesión de DB independiente.
    Soporta cancelación: si el cliente se desconecta, devuelve resumen parcial.
    """
    folder_path = Path(body.folder_path)

    if not folder_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Carpeta no encontrada: {folder_path}",
        )
    if not folder_path.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"La ruta no es una carpeta: {folder_path}",
        )

    archivos = sorted(
        list(folder_path.glob("*.gif")) + list(folder_path.glob("*.png"))
    )

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
                    "archivo": archivo.name,
                    "imagen_id": resultado.imagen_id,
                    "exito": True,
                    "pixeles_originales": m.pixeles_originales,
                    "pixeles_limpios": m.pixeles_limpios,
                    "pixeles_rellenados": m.pixeles_rellenados,
                    "pixeles_perdidos": m.pixeles_perdidos,
                    "error_relleno_pct": float(m.error_relleno_pct),
                    "score_match": float(m.score_match),
                    "tiene_marco": m.tiene_marco,
                    "mensaje_error": "",
                })

            except PipelineCanceladoError:
                await file_db.rollback()
                cancelado = True
                resultados.append({
                    "archivo": archivo.name,
                    "imagen_id": None,
                    "exito": False,
                    "mensaje_error": "Cancelado por el cliente",
                })
                break

            except ValueError as e:
                await file_db.rollback()
                fallidos += 1
                resultados.append({
                    "archivo": archivo.name,
                    "imagen_id": None,
                    "exito": False,
                    "mensaje_error": str(e),
                })

            except Exception as e:
                await file_db.rollback()
                fallidos += 1
                resultados.append({
                    "archivo": archivo.name,
                    "imagen_id": None,
                    "exito": False,
                    "mensaje_error": f"{type(e).__name__}: {str(e)[:200]}",
                })

    return BatchPipelineResponse(
        total=len(archivos),
        exitosos=exitosos,
        fallidos=fallidos,
        resultados=resultados,
        cancelado=cancelado,
    )


@router.post("/upload-lote", response_model=BatchPipelineResponse, status_code=status.HTTP_200_OK)
async def procesar_upload_lote(
    http_request: Request,
    archivos: list[UploadFile] = File(...),
    _user: dict = Depends(get_current_user),
) -> BatchPipelineResponse:
    """
    Recibe archivos .gif/.png desde el cliente (upload), los guarda en /tmp/,
    los procesa secuencialmente con el pipeline completo y limpia los temporales al finalizar.

    Soporta cancelación: si el cliente se desconecta, devuelve resumen parcial.
    """
    tmp_dir = tempfile.mkdtemp(prefix="radar_lote_")
    try:
        # Guardar archivos subidos en directorio temporal
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

            if await http_request.is_disconnected():
                cancelado = True
                break

            async with AsyncSessionLocal() as file_db:
                try:
                    resultado = await ejecutar_pipeline_local(path, file_db, request=http_request)
                    await file_db.commit()
                    exitosos += 1
                    m = resultado.metricas
                    resultados.append({
                        "archivo": path.name,
                        "imagen_id": resultado.imagen_id,
                        "exito": True,
                        "pixeles_originales": m.pixeles_originales,
                        "pixeles_limpios": m.pixeles_limpios,
                        "pixeles_rellenados": m.pixeles_rellenados,
                        "pixeles_perdidos": m.pixeles_perdidos,
                        "error_relleno_pct": float(m.error_relleno_pct),
                        "score_match": float(m.score_match),
                        "tiene_marco": m.tiene_marco,
                        "mensaje_error": "",
                    })
                except PipelineCanceladoError:
                    await file_db.rollback()
                    cancelado = True
                    resultados.append({
                        "archivo": path.name,
                        "imagen_id": None,
                        "exito": False,
                        "mensaje_error": "Cancelado por el cliente",
                    })
                    break
                except Exception as e:
                    await file_db.rollback()
                    fallidos += 1
                    resultados.append({
                        "archivo": path.name,
                        "imagen_id": None,
                        "exito": False,
                        "mensaje_error": f"{type(e).__name__}: {str(e)[:200]}",
                    })

        return BatchPipelineResponse(
            total=len(paths),
            exitosos=exitosos,
            fallidos=fallidos,
            resultados=resultados,
            cancelado=cancelado,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


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