# src/subsistema1/orquestador.py
"""
Orquestador del pipeline de 7 fases del Subsistema 1.

Coordina todas las fases en orden:
1. Adquisición (ingestor)
2. Detección de marco (detector_marco)
3. Recorte condicional (crop)
4. Limpieza (limpiar)
5. Relleno de huecos (rellenar)
6. Geolocalización (geolocalizar)
7. Persistencia (repository)

No escribe nada a disco. Todo se mantiene en memoria (numpy arrays, BytesIO).
Las métricas de calidad se devuelven al llamador para persistencia.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repository import (
    ImagenRadarRepository,
    IntentoDescargaRepository,
    MetricaProcesamientoRepository,
    ProcesamentoPasoRepository,
)
from src.subsistema1.crop import crop_imagen
from src.subsistema1.detector_marco import detectar_marco
from src.subsistema1.geolocalizar import GeoResultado, geolocalizar
from src.subsistema1.ingestor import IngestaResultado, ingestar_local, ingestar_url
from src.subsistema1.limpiar import clean_image
from src.subsistema1.rellenar import fill_gaps

logger = logging.getLogger(__name__)


@dataclass
class MetricasPipeline:
    """Métricas de calidad del pipeline (para persistencia y logging)."""

    pixeles_originales: int = 0
    pixeles_limpios: int = 0
    pixeles_rellenados: int = 0
    pixeles_perdidos: int = 0
    error_relleno_pct: float = 0.0
    tiene_marco: bool = False
    score_match: float = 0.0
    geo: GeoResultado | None = None


@dataclass
class ResultadoPipeline:
    """Resultado completo del pipeline para una imagen."""

    imagen_id: int
    metricas: MetricasPipeline
    exito: bool
    mensaje_error: str = ""


def _calcular_metricas(
    clean_rgb: np.ndarray,
    filled_rgb: np.ndarray,
    dbz_map: np.ndarray,
) -> dict[str, int | float]:
    """
    Calcula métricas de calidad comparando imagen limpia vs rellenada.

    Args:
        clean_rgb: Array (H, W, 3) post-limpieza.
        filled_rgb: Array (H, W, 3) post-relleno.
        dbz_map: Array (H, W) int32 con valores dBZ (0 = no tormenta).

    Returns:
        Diccionario con pixeles_originales, limpios, rellenados, perdidos y error_pct.
    """
    originales = int(np.count_nonzero(dbz_map))
    limpios = int(np.count_nonzero(np.any(clean_rgb > 0, axis=2)))
    rellenos_mask = np.any(filled_rgb > 0, axis=2) & ~np.any(clean_rgb > 0, axis=2)
    rellenados = int(np.count_nonzero(rellenos_mask))
    perdidos = max(0, originales - limpios)
    error_pct = round((perdidos / originales * 100) if originales > 0 else 0.0, 2)

    return {
        "pixeles_originales": originales,
        "pixeles_limpios": limpios,
        "pixeles_rellenados": rellenados,
        "pixeles_perdidos": perdidos,
        "error_relleno_pct": error_pct,
    }


def _array_to_png_bytes(arr: np.ndarray) -> bytes:
    """Convierte un array (H, W, 3) uint8 a bytes PNG en memoria."""
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8), mode="RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


async def ejecutar_pipeline_local(
    file_path: Path,
    session: AsyncSession,
) -> ResultadoPipeline:
    """
    Ejecuta el pipeline completo para un archivo local (Ruta A).

    Args:
        file_path: Ruta al archivo PNG o GIF local.
        session: Sesión async de SQLAlchemy.

    Returns:
        ResultadoPipeline con el ID de la imagen y las métricas.
    """
    img_repo = ImagenRadarRepository(session)
    paso_repo = ProcesamentoPasoRepository(session)
    metrica_repo = MetricaProcesamientoRepository(session)

    # ── Fase 1: Adquisición ───────────────────────────────────────────────────
    ingesta: IngestaResultado = await ingestar_local(file_path)

    # Verificar duplicado
    if await img_repo.existe_duplicado(ingesta.fecha_hora, "local"):
        logger.warning("Duplicado detectado: %s %s", ingesta.fecha_hora, "local")
        raise ValueError(f"Imagen duplicada para fecha_hora={ingesta.fecha_hora} origen=local")

    imagen = await img_repo.crear(ingesta.fecha_hora, "local", ingesta.raw_bytes)
    imagen_id = imagen.id
    await img_repo.actualizar_estado(imagen_id, "procesando")

    return await _ejecutar_fases_comunes(
        imagen_id=imagen_id,
        pil_image=ingesta.imagen_pil,
        raw_bytes=ingesta.raw_bytes,
        img_repo=img_repo,
        paso_repo=paso_repo,
        metrica_repo=metrica_repo,
    )


async def ejecutar_pipeline_url(
    session: AsyncSession,
    url: str | None = None,
) -> ResultadoPipeline:
    """
    Ejecuta el pipeline completo para la descarga desde URL DACC (Ruta B).

    Args:
        session: Sesión async de SQLAlchemy.
        url: URL de descarga. Si None, usa settings.radar_url.

    Returns:
        ResultadoPipeline con el ID de la imagen y las métricas.
    """
    img_repo = ImagenRadarRepository(session)
    paso_repo = ProcesamentoPasoRepository(session)
    metrica_repo = MetricaProcesamientoRepository(session)
    intento_repo = IntentoDescargaRepository(session)

    from src.config import settings
    target_url = url or settings.radar_url

    try:
        ingesta = await ingestar_url(target_url)
        await intento_repo.registrar(target_url, exitoso=True)
    except Exception as e:
        await intento_repo.registrar(target_url, exitoso=False, motivo_fallo=str(e)[:100])
        raise

    # Verificar duplicado
    if await img_repo.existe_duplicado(ingesta.fecha_hora, "url"):
        logger.warning("Duplicado URL detectado: %s", ingesta.fecha_hora)
        raise ValueError(f"Imagen duplicada para fecha_hora={ingesta.fecha_hora} origen=url")

    imagen = await img_repo.crear(ingesta.fecha_hora, "url", ingesta.raw_bytes)
    imagen_id = imagen.id
    await img_repo.actualizar_estado(imagen_id, "procesando")

    return await _ejecutar_fases_comunes(
        imagen_id=imagen_id,
        pil_image=ingesta.imagen_pil,
        raw_bytes=ingesta.raw_bytes,
        img_repo=img_repo,
        paso_repo=paso_repo,
        metrica_repo=metrica_repo,
    )


async def _ejecutar_fases_comunes(
    imagen_id: int,
    pil_image: Image.Image,
    raw_bytes: bytes,
    img_repo: ImagenRadarRepository,
    paso_repo: ProcesamentoPasoRepository,
    metrica_repo: MetricaProcesamientoRepository,
) -> ResultadoPipeline:
    """
    Fases 2-7 comunes a ambas rutas de ingesta.

    Args:
        imagen_id: ID del registro en base de datos.
        pil_image: Imagen PIL en memoria.
        raw_bytes: Bytes crudos originales.
        img_repo / paso_repo / metrica_repo: Repositorios ya inicializados.

    Returns:
        ResultadoPipeline con métricas completas.
    """
    metricas = MetricasPipeline()
    cropped_png_bytes: bytes | None = None

    try:
        # ── Fase 2: Detección de marco ────────────────────────────────────────
        tiene_marco = detectar_marco(pil_image)
        metricas.tiene_marco = tiene_marco
        logger.info("[img=%d] Fase 2 — tiene_marco=%s", imagen_id, tiene_marco)
        await paso_repo.registrar(imagen_id, "deteccion_marco")

        # ── Fase 3: Recorte condicional ───────────────────────────────────────
        if tiene_marco:
            cropped_arr = crop_imagen(pil_image)
            current_image = Image.fromarray(cropped_arr.astype(np.uint8), mode="RGB")
            cropped_png_bytes = _array_to_png_bytes(cropped_arr)
            logger.info("[img=%d] Fase 3 — crop aplicado: %s", imagen_id, cropped_arr.shape)
        else:
            current_image = pil_image
            logger.info("[img=%d] Fase 3 — sin marco, crop omitido", imagen_id)
        await paso_repo.registrar(imagen_id, "crop")

        # ── Fase 4: Limpieza ──────────────────────────────────────────────────
        clean_rgb, gap_mask, dbz_map = clean_image(current_image)
        clean_png_bytes = _array_to_png_bytes(clean_rgb)
        logger.info("[img=%d] Fase 4 — limpieza ok, storm_pixels=%d", imagen_id, int(np.count_nonzero(dbz_map)))
        await paso_repo.registrar(imagen_id, "limpieza")

        # ── Fase 5: Relleno ───────────────────────────────────────────────────
        filled_rgb = fill_gaps(clean_rgb, gap_mask)
        filled_png_bytes = _array_to_png_bytes(filled_rgb)
        logger.info("[img=%d] Fase 5 — relleno ok", imagen_id)
        await paso_repo.registrar(imagen_id, "relleno")

        # ── Calcular métricas de calidad ──────────────────────────────────────
        stats = _calcular_metricas(clean_rgb, filled_rgb, dbz_map)
        metricas.pixeles_originales = stats["pixeles_originales"]
        metricas.pixeles_limpios = stats["pixeles_limpios"]
        metricas.pixeles_rellenados = stats["pixeles_rellenados"]
        metricas.pixeles_perdidos = stats["pixeles_perdidos"]
        metricas.error_relleno_pct = stats["error_relleno_pct"]

        # ── Fase 6: Geolocalización ───────────────────────────────────────────
        geo = geolocalizar(filled_rgb)
        metricas.geo = geo
        metricas.score_match = geo.score_match
        logger.info("[img=%d] Fase 6 — geo ok, score=%.4f", imagen_id, geo.score_match)
        await paso_repo.registrar(imagen_id, "geolocalizacion")

        # ── Fase 7: Persistencia ──────────────────────────────────────────────
        await img_repo.actualizar_completado(
            imagen_id,
            geotiff_data=geo.geotiff_bytes,
            clean_data=clean_png_bytes,
            filled_data=filled_png_bytes,
            cropped_data=cropped_png_bytes,
            transform_affine=geo.transform_affine,
            crs=geo.crs_str,
            score_match=geo.score_match,
            tiene_marco=tiene_marco,
        )
        await metrica_repo.guardar(
            imagen_id=imagen_id,
            pixeles_originales=metricas.pixeles_originales,
            pixeles_limpios=metricas.pixeles_limpios,
            pixeles_rellenados=metricas.pixeles_rellenados,
            pixeles_perdidos=metricas.pixeles_perdidos,
            error_relleno_pct=metricas.error_relleno_pct,
        )
        logger.info("[img=%d] Fase 7 — persistido con éxito", imagen_id)

        return ResultadoPipeline(imagen_id=imagen_id, metricas=metricas, exito=True)

    except Exception as exc:
        logger.exception("[img=%d] Error en pipeline: %s", imagen_id, exc)
        await img_repo.marcar_error(imagen_id)
        await paso_repo.registrar(
            imagen_id, "limpieza", exitoso=False, mensaje_error=str(exc)[:500]
        )
        return ResultadoPipeline(
            imagen_id=imagen_id,
            metricas=metricas,
            exito=False,
            mensaje_error=str(exc),
        )