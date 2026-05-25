# src/subsistema1/geolocalizar.py
"""
Fase 6 del pipeline: Geolocalización mediante template matching del eco fijo.

Corrige el Affine Transform de la imagen comparando la posición del eco fijo
(estructura geográfica permanente) con su posición real conocida.

Sin I/O directo al pipeline principal: escribe el GeoTIFF final a un buffer
BytesIO que se persiste en la base de datos.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

import cv2
import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import Affine

from src.config import settings

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────
THRESHOLD_WIDTH: int = settings.template_width_threshold  # 799
MIN_MATCH_SCORE: float = settings.match_score_min          # 0.3
COMPRESS: str = "lzw"


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_template_paths(width: int) -> tuple[Path, Path]:
    """
    Devuelve las rutas de (template_geo, template_eco_fijo) según el ancho.

    - tif700.tif → imágenes ≤ 799px de ancho.
    - tif800.tif → imágenes > 799px de ancho.
    - template_eco_fijo.tif → ancla geográfica siempre igual.

    Args:
        width: Ancho de la imagen procesada.

    Returns:
        Tupla (ruta_template_geo, ruta_template_eco_fijo).

    Raises:
        FileNotFoundError: Si algún template no existe en template_dir.
    """
    template_dir = Path(settings.template_dir)
    geo_name = "tif800.tif" if width > THRESHOLD_WIDTH else "tif700.tif"
    geo_path = template_dir / geo_name
    eco_path = template_dir / "template_eco_fijo.tif"

    if not geo_path.exists():
        raise FileNotFoundError(f"Template de georreferencia no encontrado: {geo_path}")
    if not eco_path.exists():
        raise FileNotFoundError(f"Template eco fijo no encontrado: {eco_path}")

    return geo_path, eco_path


def extract_shape_mask(arr: np.ndarray, threshold: int = 10) -> np.ndarray:
    """
    Extrae máscara binaria de FORMA de una imagen.

    - RGBA: usa el canal alpha (alpha > threshold → forma).
    - RGB: cualquier canal > threshold → forma.
    - 2D: valor > threshold → forma.

    Args:
        arr: Array numpy (H, W) o (H, W, 3) o (H, W, 4).
        threshold: Valor mínimo de píxel para considerar que es forma.

    Returns:
        Máscara uint8 con 255=forma, 0=fondo.
    """
    if arr.ndim == 2:
        return (arr > threshold).astype(np.uint8) * 255
    if arr.shape[2] == 4:
        return (arr[:, :, 3] > threshold).astype(np.uint8) * 255
    return (np.any(arr[:, :, :3] > threshold, axis=2)).astype(np.uint8) * 255


def match_template_binary(
    image_mask: np.ndarray,
    template_mask: np.ndarray,
) -> tuple[tuple[int, int], float]:
    """
    Template matching sobre máscaras binarias usando TM_CCOEFF_NORMED.

    Args:
        image_mask: Máscara de la imagen de radar (H, W) uint8.
        template_mask: Máscara del eco fijo (h, w) uint8 con h<H y w<W.

    Returns:
        Tupla ((col, fila), score) donde (col, fila) es la esquina sup-izq del match.
    """
    image_f = image_mask.astype(np.float32)
    template_f = template_mask.astype(np.float32)
    result = cv2.matchTemplate(image_f, template_f, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    return max_loc, float(max_val)


def pixel_to_geo(transform: Affine, col: float, row: float) -> tuple[float, float]:
    """
    Convierte coordenadas de píxel a coordenadas geográficas usando el Affine Transform.

    Args:
        transform: Transform affine del raster.
        col: Columna (eje X).
        row: Fila (eje Y).

    Returns:
        Tupla (longitud, latitud).
    """
    lon, lat = transform * (col, row)
    return lon, lat


def get_center_geo(
    transform: Affine, width: int, height: int
) -> tuple[float, float]:
    """
    Calcula las coordenadas geográficas del centro exacto de un raster.

    Args:
        transform: Transform affine del raster.
        width: Ancho en píxeles.
        height: Alto en píxeles.

    Returns:
        Tupla (longitud, latitud) del centro.
    """
    center_col = (width - 1) / 2.0
    center_row = (height - 1) / 2.0
    return pixel_to_geo(transform, center_col, center_row)


def correct_transform(
    original_transform: Affine,
    delta_lon: float,
    delta_lat: float,
) -> Affine:
    """
    Corrige el Affine Transform sumando el delta al origen (c, f).

    Args:
        original_transform: Transform affine original del template de referencia.
        delta_lon: Desplazamiento en longitud (grados).
        delta_lat: Desplazamiento en latitud (grados).

    Returns:
        Nuevo Affine Transform corregido.
    """
    a, b, c, d, e, f = original_transform[:6]
    return Affine(a, b, c + delta_lon, d, e, f + delta_lat)


def array_to_geotiff_bytes(
    arr: np.ndarray,
    transform: Affine,
    crs: object,
    compress: str = COMPRESS,
    nodata: int | None = 0,
) -> bytes:
    """
    Convierte un array numpy a bytes de GeoTIFF en memoria (sin escribir a disco).

    Args:
        arr: Array (H, W) o (H, W, C) uint8.
        transform: Affine Transform corregido.
        crs: Sistema de referencia de coordenadas (ej: EPSG:4326).
        compress: Algoritmo de compresión ('lzw', 'deflate', 'none').
        nodata: Valor NoData del raster (default=0, píxel negro = sin datos).

    Returns:
        Bytes del GeoTIFF listo para persistir en base de datos.
    """
    if arr.ndim == 3:
        height, width, count = arr.shape
        bands = [arr[:, :, i] for i in range(count)]
    else:
        height, width = arr.shape
        count = 1
        bands = [arr]

    buffer = io.BytesIO()
    with rasterio.open(
        buffer,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=count,
        dtype=arr.dtype,
        crs=crs,
        transform=transform,
        compress=compress,
        nodata=nodata,
    ) as dst:
        for i, band in enumerate(bands, start=1):
            dst.write(band, i)

    buffer.seek(0)
    return buffer.read()


# ── API pública ───────────────────────────────────────────────────────────────

class GeoResultado:
    """Resultado completo de la geolocalización."""

    __slots__ = (
        "geotiff_bytes",
        "transform_affine",
        "crs_str",
        "score_match",
        "delta_lon",
        "delta_lat",
        "clutter_mask",  # máscara booleana H×W de ecos fijos en la imagen
    )

    def __init__(
        self,
        geotiff_bytes: bytes,
        transform_affine: str,
        crs_str: str,
        score_match: float,
        delta_lon: float,
        delta_lat: float,
        clutter_mask: np.ndarray | None = None,
    ) -> None:
        self.geotiff_bytes = geotiff_bytes
        self.transform_affine = transform_affine
        self.crs_str = crs_str
        self.score_match = score_match
        self.delta_lon = delta_lon
        self.delta_lat = delta_lat
        self.clutter_mask = clutter_mask


def geolocalizar(filled_rgb: np.ndarray) -> GeoResultado:
    """
    Pipeline completo de geolocalización para un array RGB de radar.

    Pasos:
    1. Elegir template de georreferencia (tif700 o tif800) según ancho.
    2. Leer CRS y Transform del template.
    3. Extraer máscara de forma del array.
    4. Cargar template_eco_fijo y extraer su máscara de forma.
    5. Template matching binario: encontrar dónde está el eco en la imagen.
    6. Calcular delta geográfico entre posición encontrada y posición real.
    7. Corregir el Affine Transform.
    8. Construir máscara booleana de clutter (ecos fijos) en coordenadas de imagen.
    9. Generar GeoTIFF final en memoria (BytesIO), con píxeles de clutter
       puestos a 0 (NoData) para que no aparezcan como precipitación real.

    Args:
        filled_rgb: Array (H, W, 3) uint8. Imagen post-relleno de huecos.

    Returns:
        GeoResultado con los bytes del GeoTIFF sin ecos fijos, metadatos de
        geolocalización y clutter_mask (máscara booleana H×W de la zona de
        ecos fijos, útil para métricas y template matching).

    Raises:
        FileNotFoundError: Si los templates no están en template_dir.
        ValueError: Si el template eco es más grande que la imagen.
    """
    height, width = filled_rgb.shape[:2]

    # ── 1. Elegir templates ───────────────────────────────────────────────────
    geo_path, eco_path = get_template_paths(width)
    logger.info("Template geo: %s | Eco: %s", geo_path.name, eco_path.name)

    # ── 2. Leer CRS y Transform de referencia ────────────────────────────────
    with rasterio.open(geo_path) as src_geo:
        ref_transform = src_geo.transform
        ref_crs = src_geo.crs
    logger.info("CRS: %s | Transform: %s", ref_crs, ref_transform)

    # ── 3. Extraer máscara de forma del array ─────────────────────────────────
    png_mask = extract_shape_mask(filled_rgb)

    # ── 4. Cargar eco fijo y su máscara ──────────────────────────────────────
    with rasterio.open(eco_path) as src_eco:
        eco_arr = np.moveaxis(src_eco.read(), 0, -1)  # (C, H, W) → (H, W, C)
        eco_transform = src_eco.transform
        eco_width = src_eco.width
        eco_height = src_eco.height

    eco_mask = extract_shape_mask(eco_arr)

    # Verificar que el template cabe en la imagen
    eco_h, eco_w = eco_mask.shape
    if eco_h > height or eco_w > width:
        raise ValueError(
            f"Template eco ({eco_mask.shape}) mayor que la imagen ({png_mask.shape})."
        )

    # ── 5. Template matching ──────────────────────────────────────────────────
    top_left, score = match_template_binary(png_mask, eco_mask)
    match_col, match_row = top_left
    logger.info("Match: top_left=(%d, %d), score=%.4f", match_col, match_row, score)

    if score < MIN_MATCH_SCORE:
        logger.warning("Score bajo (%.4f < %.4f). Match puede ser incorrecto.", score, MIN_MATCH_SCORE)

    # ── 6. Calcular delta geográfico ──────────────────────────────────────────
    eco_center_col = match_col + (eco_w - 1) / 2.0
    eco_center_row = match_row + (eco_h - 1) / 2.0

    # Donde quedó el eco según el transform de referencia
    eco_found_lon, eco_found_lat = pixel_to_geo(ref_transform, eco_center_col, eco_center_row)

    # Donde DEBE estar el eco (del template_eco_fijo.tif)
    eco_true_lon, eco_true_lat = get_center_geo(eco_transform, eco_width, eco_height)

    delta_lon = eco_true_lon - eco_found_lon
    delta_lat = eco_true_lat - eco_found_lat
    logger.info("Δlon=%.4f, Δlat=%.4f", delta_lon, delta_lat)

    # ── 7. Corregir Transform ─────────────────────────────────────────────────
    corrected_transform = correct_transform(ref_transform, delta_lon, delta_lat)

    # ── 8. Construir máscara booleana de clutter en coordenadas de la imagen ──
    # La zona del eco fijo ocupa [match_row:match_row+eco_h, match_col:match_col+eco_w]
    # Usamos la forma exacta del eco (eco_mask > 0) para no enmascarar de más.
    clutter_mask = np.zeros((height, width), dtype=bool)
    row_end = min(match_row + eco_h, height)
    col_end = min(match_col + eco_w, width)
    clutter_mask[match_row:row_end, match_col:col_end] = (
        eco_mask[:row_end - match_row, :col_end - match_col] > 0
    )
    logger.info(
        "[geo] clutter_mask: %d píxeles de eco fijo enmascarados",
        int(np.count_nonzero(clutter_mask)),
    )

    # ── 9. Generar GeoTIFF final en memoria, sin ecos fijos ───────────────────
    # FIX BUG 2: Se aplica la clutter_mask ANTES de escribir el GeoTIFF.
    # Los píxeles de eco fijo (montaña/terreno) se ponen a 0 (NoData) para
    # que el raster exportado muestre únicamente precipitación real.
    # El array original filled_rgb NO se modifica (se trabaja sobre una copia),
    # para no afectar el template matching ni el cálculo de métricas del orquestador.
    export_rgb = filled_rgb.copy()
    export_rgb[clutter_mask] = 0
    logger.info("[geo] GeoTIFF exportado con ecos fijos enmascarados (NoData=0)")

    geotiff_bytes = array_to_geotiff_bytes(export_rgb, corrected_transform, ref_crs)

    return GeoResultado(
        geotiff_bytes=geotiff_bytes,
        transform_affine=str(corrected_transform),
        crs_str=str(ref_crs),
        score_match=score,
        delta_lon=delta_lon,
        delta_lat=delta_lat,
        clutter_mask=clutter_mask,
    )
