from __future__ import annotations
"""
Fase 6 del pipeline: Geolocalización.

Desde el 15/10/2026 (incidente del 13/10, ver SUBSISTEMA 1/GEO_ROBUSTO/informe_geo_robusto.tex)
la geolocalización separa dos preguntas:

  1. GEOMETRÍA del GIF (escala, proyección, dónde está el 0 km): no se adivina
     imagen por imagen. Se calibra UNA vez por variante (tamaño de recorte) y se
     guarda en templates/geometrias_gif.json. El GIF es una grilla en km centrada
     en el radar → proyección nativa azimutal equidistante (AEQD), 722,54 m/px.
  2. CORRIMIENTO de cada imagen respecto de su variante (jitter del recorte): lo
     mide el template matching del eco fijo, pero acotado y validado.

Camino robusto (imagen con variante calibrada):
  capa 0    cargar_geometrias / elegir_geometria
  capa 1    template_a_dbz / mascara_dbz / elegir_umbral   (solo ecos >= 35 dBZ)
  capa 2    buscar_en_ventana                              (±25 px de lo esperado)
  capa 4    combinar_corrimientos                          (dos templates = dos testigos)
  capa 3+5  decidir_corrimiento                            (mover solo con 2 testigos y > 3 px)
  luego     mascara_clutter (posición REAL) → _apply_dbz_filters → reproyectar (nearest)
            → GeoTIFF con etiquetas GEO_*

Camino legado (tamaño sin variante calibrada, p. ej. el banco de imágenes
irregulares): template matching en cascada de siempre (_geolocalizar_legado),
con el resultado MARCADO como "legado_sin_calibrar".

IMPORTANTE: El GeoTIFF de salida tiene 1 banda (uint8) con valores dBZ
(0=NoData, 10-80=niveles de precipitación) y Color Table.
"""
import io
import json
import logging
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import rasterio
from PIL import Image
from rasterio.crs import CRS
from rasterio.transform import Affine
from rasterio.warp import Resampling, calculate_default_transform, reproject

from src.config import settings

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────
THRESHOLD_WIDTH: int = settings.template_width_threshold  # 799
MIN_MATCH_SCORE: float = settings.match_score_min          # 0.3
COMPRESS: str = "lzw"

MIN_MATCH_SCORE_GLOBAL: float = 0.50
MIN_SHAPE_IOU: float = 0.20
MIN_GLOBAL_CORR: float = 0.30
MIN_SHAPE_IOU: float = 0.30
ANCHOS = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00]

# Mapa dBZ -> color RGB (usado para Color Table en el GeoTIFF)
DBZ_COLOR_MAP = {
    10: (72, 61, 139),   # #483D8B
    20: (0, 90, 0),      # #005A00
    30: (0, 112, 0),     # #007000
    35: (8, 127, 219),   # #087FDB
    36: (28, 71, 232),   # #1C47E8
    39: (110, 13, 198),  # #6E0DC6
    42: (200, 15, 134),  # #C80F86
    45: (192, 100, 135), # #C06487
    48: (210, 136, 59),  # #D2883B
    51: (250, 196, 49),  # #FAC431
    54: (252, 252, 12),  # #FCFC0C
    57: (254, 154, 88),  # #FE9A58
    60: (254, 95, 5),    # #FE5F05
    65: (253, 52, 28),   # #FD341C
    70: (190, 190, 190), # #BEBEBE
    80: (211, 211, 211), # #D3D3D3
}

# ── Color Table para GeoTIFF ─────────────────────────────────────────────────

def _build_color_table() -> dict:
    """
    Construye la Color Table para rasterio.

    Cada entrada: valor_dBZ -> (R, G, B, A)
    NoData=0 -> transparente
    """
    color_table = {}
    for dbz, (r, g, b) in DBZ_COLOR_MAP.items():
        color_table[dbz] = (r, g, b, 255)  # Alpha=255 (opaco)
    # NoData transparente
    color_table[0] = (0, 0, 0, 0)
    return color_table


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_template_paths(width: int | None = None) -> tuple[Path | None, Path]:
    """
    Mantenido por retrocompatibilidad. Devuelve (template_geo_opcional, template_eco_fijo_principal).
    La geolocalización actual se basa exclusivamente en los templates de eco fijo.
    """
    template_dir = Path(settings.template_dir)
    eco_paths = _get_eco_template_paths(template_dir)
    geo_path = None
    if width is not None:
        candidate = template_dir / ("tif800.tif" if width > THRESHOLD_WIDTH else "tif700.tif")
        if candidate.exists():
            geo_path = candidate
    return geo_path, eco_paths[0]


def _get_eco_template_paths(template_dir: Path | None = None) -> list[Path]:
    """
    Devuelve todos los templates eco disponibles (al menos uno debe existir).
    Soporta template_eco_fijo.tif y template_eco_fijo2.tif.
    """
    if template_dir is None:
        template_dir = Path(settings.template_dir)
    names = ["template_eco_fijo.tif", "template_eco_fijo2.tif"]
    paths = [template_dir / n for n in names if (template_dir / n).exists()]
    if not paths:
        raise FileNotFoundError(
            f"No se encontró ningún template eco en {template_dir}"
        )
    return paths


def extract_shape_mask(arr: np.ndarray, threshold: int = 10) -> np.ndarray:
    """
    Extrae máscara binaria de FORMA de una imagen.

    - RGBA: usa el canal alpha (alpha > threshold → forma).
    - RGB: cualquier canal > threshold → forma.
    - 2D: valor > threshold → forma.
    """
    if arr.ndim == 2:
        return (arr > threshold).astype(np.uint8) * 255
    if arr.shape[2] == 4:
        return (arr[:, :, 3] > threshold).astype(np.uint8) * 255
    return (np.any(arr[:, :, :3] > threshold, axis=2)).astype(np.uint8) * 255


# ── Verificación de forma (IoU + Correlación) ────────────────────────────────

def _extract_region(image_mask: np.ndarray, top_left: tuple,
                    tmpl_h: int, tmpl_w: int) -> np.ndarray:
    col0, row0 = int(top_left[0]), int(top_left[1])
    ih, iw = image_mask.shape[:2]
    r0, r1 = max(row0, 0), min(row0 + tmpl_h, ih)
    c0, c1 = max(col0, 0), min(col0 + tmpl_w, iw)
    mr0, mc0 = r0 - row0, c0 - col0
    region = np.zeros((tmpl_h, tmpl_w), dtype=np.uint8)
    if r1 > r0 and c1 > c0:
        region[mr0:mr0 + (r1 - r0), mc0:mc0 + (c1 - c0)] = image_mask[r0:r1, c0:c1]
    return region


def verify_iou(image_mask: np.ndarray, template_mask: np.ndarray,
               top_left: tuple) -> tuple[float, bool]:
    '''
    esta función calcula la intersección sobre unión (IoU) entre la máscara de la imagen y la máscara del template en la posición top_left.
    sirve para verificar si la forma del eco fijo en la imagen coincide con la forma del template de eco fijo.
    explicación de la función:
    1. extrae la región de la máscara de la imagen correspondiente a la posición del template.
    2. calcula la intersección y la unión entre la región extraída y la máscara del template, con esta formula: 
        IoU = (intersección) / (unión), el resultado obtenido es un valor entre 0 y 1, donde 1 indica una coincidencia perfecta y 0 indica que no hay superposición.
        intersección es la cantidad de píxeles donde ambas máscaras son 255 (blanco), y unión es la cantidad de píxeles donde al menos una de las máscaras es 255.
        Explicado con manzanas, si la región extraída de la imagen y la máscara del template tienen muchos píxeles blancos en común, 
        la intersección será grande y la IoU será alta.

    3. devuelve la IoU y un booleano que indica si la IoU es mayor o igual al umbral mínimo (MIN_SHAPE_IOU).
    
    '''
    th, tw = template_mask.shape[:2]
    region = _extract_region(image_mask, top_left, th, tw)
    a, b = region == 255, template_mask == 255
    union = np.logical_or(a, b).sum()
    iou = float(np.logical_and(a, b).sum()) / float(union) if union > 0 else 0.0
    return iou, iou >= MIN_SHAPE_IOU


def verify_corr(image_mask: np.ndarray, template_mask: np.ndarray,
                top_left: tuple) -> tuple[float, bool]:
    '''
    esta función calcula la correlación entre la región de la máscara de la imagen y la máscara del template en la posición top_left.
    sirve para verificar si la forma del eco fijo en la imagen coincide con la forma del template de eco fijo.
    explicación de la función:
    1. extrae la región de la máscara de la imagen correspondiente a la posición del template.
    2. calcula la correlación entre la región extraída y la máscara del template usando cv2.matchTemplate con el método TM_CCOEFF_NORMED.
        si ocurre un error (por ejemplo, si las máscaras son demasiado pequeñas), se calcula la correlación manualmente usando np.corrcoef.
        el resultado es un valor entre -1 y 1, donde 1 indica una correlación perfecta, 0 indica ninguna correlación y -1 indica una correlación inversa.  
    3. devuelve la correlación y un booleano que indica si la correlación es mayor o igual al umbral mínimo (MIN_GLOBAL_CORR).

    la diferencia con verify_iou es que la correlación mide la similitud de los patrones de las máscaras, mientras que IoU mide la superposición espacial.
    son cosas difentes? respuesta: sí, son cosas diferentes. se usan ambas? respuesta: sí, se usan ambas para tener una verificación más robusta de la coincidencia entre la imagen y el template.
    cada una nos indica algo diferente sobre la relación entre la forma del eco fijo en la imagen y la forma del template de eco fijo.
    verify_iou nos dice qué tan bien se superponen las formas, mientras que verify_corr nos dice qué tan similares son los patrones de las formas.
    corr significa correlación, es una medida estadística que indica la relación entre dos variables. en este caso, nos dice qué tan similares son los patrones de las máscaras.
    IoU significa intersección sobre unión, es una métrica que mide la superposición entre dos formas. en este caso, nos dice qué tan bien se superponen las formas de las máscaras.
    La formula de corr es:
    corr = (sum((x - mean(x)) * (y - mean(y))) / (std(x) * std(y) * len(x))) if std(x) > 0 and std(y) > 0 else 0.0  explicación de la formula:
    
    '''
    th, tw = template_mask.shape[:2]
    region = _extract_region(image_mask, top_left, th, tw).astype(np.float32)
    tmpl = template_mask.astype(np.float32)
    try:
        corr = float(cv2.matchTemplate(region, tmpl, cv2.TM_CCOEFF_NORMED)[0, 0])
    except Exception:
        r, t = region.flatten(), tmpl.flatten()
        corr = float(np.corrcoef(r, t)[0, 1]) if r.std() > 0 and t.std() > 0 else 0.0
    return corr, corr >= MIN_GLOBAL_CORR


# ── Template matching en cascada ──────────────────────────────────────────────

def _compute_result_maps(image_f: np.ndarray, template_f: np.ndarray,
                         template_mask: np.ndarray) -> list:
    """Calcula mapas de correlación disponibles (masked y/o classic)."""
    maps = []
    if np.count_nonzero(template_mask) > 0:
        try:
            maps.append(("masked", cv2.matchTemplate(
                image_f, template_f, cv2.TM_CCORR_NORMED,
                mask=template_mask.astype(np.float32),
            )))
        except cv2.error:
            pass
    try:
        maps.append(("classic", cv2.matchTemplate(image_f, template_f, cv2.TM_CCOEFF_NORMED)))
    except cv2.error:
        pass
    return maps


def _candidate_top_peaks(result_map: np.ndarray, max_candidates: int = 5,
                        min_score: float = MIN_MATCH_SCORE) -> list[tuple[int, int, float]]:
    """Devuelve los picos locales más fuertes dentro del mapa, ordenados por score."""
    safe = result_map.copy().astype(np.float32)
    safe[~np.isfinite(safe)] = -1.0
    h, w = safe.shape
    candidates: list[tuple[int, int, float]] = []
    remaining = safe.copy()

    for _ in range(max_candidates):
        if not np.any(remaining >= min_score):
            break
        idx = int(np.argmax(remaining))
        row, col = divmod(idx, w)
        score = float(remaining[row, col])
        if score < min_score:
            break
        candidates.append((row, col, score))
        r0 = max(0, row - 2)
        r1 = min(h, row + 3)
        c0 = max(0, col - 2)
        c1 = min(w, col + 3)
        remaining[r0:r1, c0:c1] = -np.inf

    return candidates


def _scan_zone(result_map: np.ndarray, image_mask: np.ndarray,
               template_mask: np.ndarray, zone_width: float,
               label: str, strict: bool = True):
    """
    Escanea la zona solicitada usando los Top-5 picos locales y selecciona
    el candidato con mejor IoU × correlación, en lugar de aceptar el máximo absoluto.
    """
    safe = result_map.copy()
    safe[~np.isfinite(safe)] = -1.0
    ih, iw = image_mask.shape
    th, tw = template_mask.shape[:2]
    n_cols = safe.shape[1]
    max_col = max(1, int(n_cols * zone_width))
    min_overlap = max(int(th * tw * 0.05), 10)
    zone = safe[:, :max_col]

    candidates: list[dict] = []
    for row, col, score in _candidate_top_peaks(zone, max_candidates=5, min_score=MIN_MATCH_SCORE):
        r1 = min(row + th, ih)
        c1 = min(col + tw, iw)
        if np.count_nonzero(image_mask[row:r1, col:c1]) < min_overlap:
            continue
        top_left = (col, row)
        iou, _ = verify_iou(image_mask, template_mask, top_left)
        corr, _ = verify_corr(image_mask, template_mask, top_left)
        combo = float(iou) * float(corr)
        if not np.isfinite(combo):
            continue
        candidates.append({
            "top_left": top_left,
            "score": float(score),
            "iou": float(iou),
            "corr": float(corr),
            "combo": combo,
        })

    if not candidates:
        return None

    best = max(candidates, key=lambda c: (c["combo"], c["iou"], c["corr"], c["score"]))
    if strict and best["iou"] < MIN_SHAPE_IOU:
        logger.info(
            "    [%s z=%.2f] sin candidato válido: mejor IoU=%.4f < %.2f",
            label, zone_width, best["iou"], MIN_SHAPE_IOU,
        )
        return None

    top_left = best["top_left"]
    score = best["score"]
    if strict:
        logger.info(
            "    [%s z=%.2f] best_combo=%.4f @ (%d,%d) iou=%.4f corr=%.4f",
            label,
            zone_width,
            best["combo"],
            top_left[0],
            top_left[1],
            best["iou"],
            best["corr"],
        )
        return top_left, score, f"{label}_combo_z{int(zone_width * 100)}"

    logger.info(
        "    [%s z=%.2f] best_raw_combo=%.4f @ (%d,%d) iou=%.4f corr=%.4f",
        label,
        zone_width,
        best["combo"],
        top_left[0],
        top_left[1],
        best["iou"],
        best["corr"],
    )
    method_name = f"{label}_raw_combo" if best["iou"] >= MIN_SHAPE_IOU else f"{label}_raw_fallback"
    return top_left, score, method_name


def _find_match_for_width(image_mask: np.ndarray, template_mask: np.ndarray,
                          result_maps: list, zone_width: float,
                          strict: bool = True):
    """Prueba los mapas en orden; devuelve el primer match encontrado o None."""
    for label, rmap in result_maps:
        match = _scan_zone(rmap, image_mask, template_mask, zone_width, label, strict)
        if match:
            return match
    return None


def match_template_binary(
    image_mask: np.ndarray,
    template_mask: np.ndarray,
    png_arr: np.ndarray | None = None,  # mantenido por compatibilidad, no usado
) -> tuple[tuple[int, int], float, str]:
    """
    Template matching sobre máscaras binarias con estrategia en cascada.

    Recorre anchos 10%→100%. Si el mismo (col, row) aparece dos veces
    consecutivas con al menos un match strict (IoU+Corr) → confirmado.
    Si no hay confirmación → usa el mejor strict; si no hay ninguno, el mejor raw.
    Fallback global a z=0.50 si ningún ancho da resultado.

    Args:
        image_mask: Máscara de la imagen de radar (H, W) uint8.
        template_mask: Máscara del eco fijo (h, w) uint8.
        png_arr: No usado (mantenido por compatibilidad con firma anterior).

    Returns:
        Tupla ((col, fila), score_forma, method_used).
    """
    image_f    = image_mask.astype(np.float32)
    template_f = template_mask.astype(np.float32)
    result_maps = _compute_result_maps(image_f, template_f, template_mask)

    if not result_maps:
        raise RuntimeError("Todos los métodos de template matching fallaron.")

    results, prev = [], None

    for width in ANCHOS:
        strict_match = _find_match_for_width(image_mask, template_mask, result_maps, width, strict=True)
        match = strict_match or _find_match_for_width(image_mask, template_mask, result_maps, width, strict=False)
        is_strict = strict_match is not None

        if match:
            (col, row), score, method = match
            logger.info("  [z=%.2f] (%d,%d) score=%.4f [%s] strict=%s",
                        width, col, row, score, method, is_strict)
            if prev and col == prev[0] and row == prev[1]:
                if is_strict or prev[5]:
                    logger.info("  ✓ CONFIRMADO en z=%.2f y z=%.2f @ (%d,%d)",
                                prev[3], width, col, row)
                    return (col, row), score, f"{method}_confirmed"
                else:
                    logger.info("  ~ repetición raw+raw ignorada @ (%d,%d)", col, row)
            results.append((col, row, score, width, method, is_strict))
            prev = (col, row, score, width, method, is_strict)
        else:
            logger.info("  [z=%.2f] sin match", width)
            prev = None

    if results:
        strict_results = [r for r in results if r[5]]
        pool = strict_results if strict_results else results
        best = max(pool, key=lambda r: r[2])
        logger.warning("  Sin confirmación. Mejor%s: z=%.2f @ (%d,%d)",
                       "(strict)" if strict_results else "(raw)",
                       best[3], best[0], best[1])
        return (best[0], best[1]), best[2], f"{best[4]}_best"

    # Fallback global
    logger.warning("  Ningún ancho dio match. Fallback global z=0.50.")
    for label, rmap in result_maps:
        match = _scan_zone(rmap, image_mask, template_mask, 0.50, label, strict=False)
        if match:
            (col, row), score, _ = match
            iou, iou_ok = verify_iou(image_mask, template_mask, (col, row))
            corr, corr_ok = verify_corr(image_mask, template_mask, (col, row))
            status = ("fallback_ok"
                      if (score >= MIN_MATCH_SCORE_GLOBAL and iou_ok and corr_ok)
                      else "fallback_unreliable")
            return (col, row), score, status

    logger.warning("  Fallback sin resultado. Devolviendo (0,0).")
    return (0, 0), 0.0, "fallback"


# ── Selección entre múltiples templates eco ───────────────────────────────────

def _best_eco_match(png_mask: np.ndarray, results: list) -> dict:
    """
    Elige el mejor match entre múltiples templates eco.

    Reglas (en orden):
    1. Si dos o más coinciden en (col, row) → ese es el eco (máxima confianza).
    2. Si no coinciden → el que tenga mejor IoU × Corr combinado.
    """
    if len(results) == 1:
        return results[0]

    # Regla 1: coincidencia de posición
    for i, a in enumerate(results):
        for b in results[i + 1:]:
            if a["col"] == b["col"] and a["row"] == b["row"]:
                logger.info("  ✓ COINCIDENCIA entre templates @ (%d,%d)", a["col"], a["row"])
                return a if a["score"] >= b["score"] else b

    # Regla 2: mejor IoU × Corr
    for r in results:
        iou, _ = verify_iou(r["png_mask"], r["eco_mask"], (r["col"], r["row"]))
        corr, _ = verify_corr(r["png_mask"], r["eco_mask"], (r["col"], r["row"]))
        r["forma"] = iou * corr

    best = max(results, key=lambda r: r["forma"])
    logger.info("  Sin coincidencia. Mejor forma: %s IoU×Corr=%.4f @ (%d,%d)",
                best["template"], best["forma"], best["col"], best["row"])
    return best


# ── Geo helpers ───────────────────────────────────────────────────────────────

def pixel_to_geo(transform: Affine, col: float, row: float) -> tuple[float, float]:
    """Convierte coordenadas de píxel a coordenadas geográficas."""
    lon, lat = transform * (col, row)
    return lon, lat


def get_center_geo(transform: Affine, width: int, height: int) -> tuple[float, float]:
    """Calcula las coordenadas geográficas del centro exacto de un raster."""
    center_col = (width - 1) / 2.0
    center_row = (height - 1) / 2.0
    return pixel_to_geo(transform, center_col, center_row)


def correct_transform(
    original_transform: Affine,
    delta_lon: float,
    delta_lat: float,
) -> Affine:
    """Corrige el Affine Transform sumando el delta al origen (c, f)."""
    a, b, c, d, e, f = original_transform[:6]
    return Affine(a, b, c + delta_lon, d, e, f + delta_lat)


def refine_subpixel_peak(
    result_map: np.ndarray,
    col: int,
    row: int,
) -> tuple[float, float]:
    """
    Refina la posición discreta (col, row) del pico a precisión subpíxel (decimal)
    mediante interpolación parabólica cuadrática continua en el vecindario 3x3.

    Fórmula:
        delta_x = 0.5 * (alpha - gamma) / (alpha - 2*beta + gamma)
        donde beta = R(0), alpha = R(-1), gamma = R(+1)

    Devuelve (col_subpixel, row_subpixel).
    """
    h, w = result_map.shape
    r = int(round(row))
    c = int(round(col))

    delta_c = 0.0
    delta_r = 0.0

    # Subpíxel horizontal (columnas / X)
    if 0 < c < w - 1 and 0 <= r < h:
        alpha = float(result_map[r, c - 1])
        beta  = float(result_map[r, c])
        gamma = float(result_map[r, c + 1])
        denom = alpha - 2.0 * beta + gamma
        if denom < -1e-7:  # Parábola con máximo (cóncava hacia abajo)
            delta = 0.5 * (alpha - gamma) / denom
            if -1.0 <= delta <= 1.0:
                delta_c = delta

    # Subpíxel vertical (filas / Y)
    if 0 < r < h - 1 and 0 <= c < w:
        alpha = float(result_map[r - 1, c])
        beta  = float(result_map[r, c])
        gamma = float(result_map[r + 1, c])
        denom = alpha - 2.0 * beta + gamma
        if denom < -1e-7:
            delta = 0.5 * (alpha - gamma) / denom
            if -1.0 <= delta <= 1.0:
                delta_r = delta

    return float(col) + delta_c, float(row) + delta_r


def dbz_array_to_geotiff_bytes(
    dbz_array: np.ndarray,
    transform: Affine,
    crs: object,
    compress: str = COMPRESS,
    nodata: int = 0,
    etiquetas_geo: dict[str, str] | None = None,
) -> bytes:
    """
    Convierte un array dBZ (H, W) uint8 a bytes de GeoTIFF en memoria.

    El GeoTIFF de salida tiene:
    - 1 banda (uint8) con valores dBZ: 0=NoData, 10-80=niveles de precipitación
    - CRS y Transform geoespacial para ubicación exacta
    - Compresión LZW
    - COLOR TABLE para que QGIS/ArcGIS muestren colores del radar (no escala de grises)

    Args:
        dbz_array: Array (H, W) uint8 con valores dBZ (0, 10, 20, ..., 80).
        transform: Affine Transform del raster.
        crs: Sistema de coordenadas (ej. EPSG:4326).
        compress: Algoritmo de compresión.
        nodata: Valor para píxeles sin datos (default 0).
        etiquetas_geo: Etiquetas GEO_* de trazabilidad (se ven en QGIS →
            Propiedades → Metadatos).

    Returns:
        Bytes del GeoTIFF listo para persistir o descargar.
    """
    height, width = dbz_array.shape
    color_table = _build_color_table()

    buffer = io.BytesIO()
    with rasterio.open(
        buffer, "w", driver="GTiff",
        height=height, width=width, count=1,
        dtype=dbz_array.dtype, crs=crs, transform=transform,
        compress=compress, nodata=nodata,
    ) as dst:
        dst.write(dbz_array, 1)
        # Escribir Color Table (tabla de colores) para que QGIS/ArcGIS muestren colores
        dst.write_colormap(1, color_table)
        # Escribir metadatos descriptivos
        dst.update_tags(
            DESCRIPTION="Radar DACC Mendoza - Reflectividad dBZ",
            UNIT="dBZ",
            LEVELS="10,20,30,35,36,39,42,45,48,51,54,57,60,65,70,80",
            NODATA_VALUE=str(nodata),
            SOURCE="DACC Mendoza - Radar Meteorológico",
            COLOR_TABLE="Paleta de colores dBZ estándar del radar DACC Mendoza",
            **(etiquetas_geo or {}),
        )

    buffer.seek(0)
    return buffer.read()


def _apply_dbz_filters(
    dbz_map: np.ndarray,
    clutter_mask: np.ndarray | None = None,
) -> np.ndarray:
    """
    Aplica filtros al mapa dBZ antes de exportar.

    Filtros:
    1. Eco fijo (clutter_mask): poner a 0 (NoData) los píxeles >= 35 dBZ.
    2. dBZ < 10: valores fuera de rango de reflectividad válida (10-80 dBZ) → 0.

    La marca de agua NO se filtra acá: la fase 4 (limpiar) ya restaura sus
    colores y la fase 5 (rellenar) cubre los residuos. Un filtro por color
    verde borraría la precipitación real de 20 y 30 dBZ.

    Args:
        dbz_map: Array (H, W) int32 con valores dBZ (post-relleno).
        clutter_mask: Array booleana (H, W). True donde hay ecos fijos.

    Returns:
        Array (H, W) uint8 con dBZ filtrados (0=NoData, 10-80=valores válidos).
    """
    # Convertir a uint8 (los valores 10-80 caben perfectamente)
    export_dbz = dbz_map.astype(np.uint8).copy()

    # 1. Eco fijo (forma exacta — sin margen rectangular).
    # Conservamos 10–30 dBZ en el export para no borrar ecos débiles que son
    # válidos, pero eliminamos el eco fijo fuerte cuando corresponde.
    if clutter_mask is not None and clutter_mask.shape == export_dbz.shape:
        clutter_strong = clutter_mask & (export_dbz >= 35)
        export_dbz[clutter_strong] = 0
        logger.info("  Filtro eco_fijo (>=35 dBZ): %d px → 0",
                    int(np.count_nonzero(clutter_strong)))

    # 2. dBZ < 10 (solo descartar valores menores a 10 dBZ; se preserva escala completa 10 a 80 dBZ)
    below_10_mask = (export_dbz > 0) & (export_dbz < 10)
    export_dbz[below_10_mask] = 0
    logger.info("  Filtro dBZ<10: %d px → 0", int(np.count_nonzero(below_10_mask)))

    return export_dbz


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
        "clutter_mask",
        "dbz_array",       # array dBZ exportado (1 banda, grilla de SALIDA)
        "estado_geo",      # corregido | nominal_* | legado_sin_calibrar
        "corrimiento_px",  # (dc, dr) aplicado respecto de la variante
        "variante",        # nombre de la variante calibrada (None en legado)
        "umbral_dbz",      # umbral usado para el matching
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
        dbz_array: np.ndarray | None = None,
        estado_geo: str | None = None,
        corrimiento_px: tuple[float, float] | None = None,
        variante: str | None = None,
        umbral_dbz: int | None = None,
    ) -> None:
        self.geotiff_bytes = geotiff_bytes
        self.transform_affine = transform_affine
        self.crs_str = crs_str
        self.score_match = score_match
        self.delta_lon = delta_lon
        self.delta_lat = delta_lat
        self.clutter_mask = clutter_mask
        self.dbz_array = dbz_array
        self.estado_geo = estado_geo
        self.corrimiento_px = corrimiento_px
        self.variante = variante
        self.umbral_dbz = umbral_dbz


def _geolocalizar_legado(
    filled_rgb: np.ndarray,
    dbz_map: np.ndarray,
) -> GeoResultado:
    """
    Método LEGADO (antes del 15/10/2026). Solo se usa para tamaños de imagen
    sin variante calibrada; el resultado sale marcado "legado_sin_calibrar".

    Limitaciones conocidas (informe GEO_ROBUSTO): máscara sin distinguir
    intensidad, búsqueda en casi todo el ancho, sin validación entre templates
    y escala copiada del template ganador (error de hasta ~37 km en bordes).

    Pasos:
    1. Extraer máscara de forma del array RGB (para template matching).
    2. Cargar todos los templates eco disponibles (eco fijo 1 y 2).
    3. Template matching en cascada (masked → classic) con verificación
       de forma (IoU + Corr) por ancho incremental. Se corre para cada
       template eco y se elige el mejor match.
    4. Calcular georreferenciación completa (Affine Transform) directamente
       a partir de la posición real del eco fijo (Ground Truth), su tamaño
       de píxel y su ubicación detectada en la imagen.
    5. Construir máscara booleana de clutter (ecos fijos) por forma exacta,
       sin margen rectangular para no eliminar tormenta real adyacente.
    6. Aplicar filtros al dbz_map:
       - Poner a 0 los píxeles de eco fijo (clutter_mask).
       - Poner a 0 los píxeles con dBZ < 10.
       - Poner a 0 los píxeles con color verde de marca de agua.
    7. Generar GeoTIFF final en memoria (BytesIO) con 1 banda dBZ uint8
       y Color Table para que se muestre con colores (no escala de grises).

    Args:
        filled_rgb: Array (H, W, 3) uint8. Imagen post-relleno de huecos.
        dbz_map: Array (H, W) int32. Valor dBZ de cada píxel (0 = no tormenta).

    Returns:
        GeoResultado con los bytes del GeoTIFF (1 banda dBZ + Color Table), metadatos de
        geolocalización, clutter_mask y dbz_array exportado.

    Raises:
        FileNotFoundError: Si no se encuentran templates eco en template_dir.
        ValueError: Si todos los templates eco son más grandes que la imagen.
        RuntimeError: Si todos los métodos de template matching fallan.
    """
    height, width = filled_rgb.shape[:2]
    template_dir = Path(settings.template_dir)

    # ── 1. Máscara de forma del array de entrada ──────────────────────────────
    png_mask = extract_shape_mask(filled_rgb)

    # ── 2. Cargar todos los templates eco ────────────────────────────────────
    eco_paths = _get_eco_template_paths(template_dir)
    logger.info("Templates eco: %s", [p.name for p in eco_paths])

    eco_data = []
    for eco_path in eco_paths:
        with rasterio.open(eco_path) as src_eco:
            eco_arr       = np.moveaxis(src_eco.read(), 0, -1)  # (C,H,W)→(H,W,C)
            eco_transform = src_eco.transform
            eco_crs       = src_eco.crs
            eco_w         = src_eco.width
            eco_h_px      = src_eco.height
        eco_mask = extract_shape_mask(eco_arr)
        eh, ew = eco_mask.shape
        if eh > height or ew > width:
            logger.warning("[%s] template más grande que imagen, ignorado", eco_path.name)
            continue
        eco_data.append({
            "template":      eco_path.name,
            "eco_mask":      eco_mask,
            "eco_transform": eco_transform,
            "eco_crs":       eco_crs,
            "eco_w":         eco_w,
            "eco_h":         eco_h_px,
        })
        logger.info("[%s] mask: %d px activos", eco_path.name, int(np.count_nonzero(eco_mask)))

    if not eco_data:
        raise ValueError("Ningún template eco es compatible con esta imagen (todos más grandes).")

    # ── 3. Template matching para cada template eco ───────────────────────────
    match_results = []
    for eco in eco_data:
        top_left, score, method = match_template_binary(png_mask, eco["eco_mask"])
        col, row = top_left
        logger.info("[%s] (%d,%d) score=%.4f method=%s", eco["template"], col, row, score, method)
        match_results.append({
            "template":      eco["template"],
            "col":           col,
            "row":           row,
            "score":         score,
            "method":        method,
            "eco_mask":      eco["eco_mask"],
            "eco_transform": eco["eco_transform"],
            "eco_crs":       eco["eco_crs"],
            "eco_w":         eco["eco_w"],
            "eco_h":         eco["eco_h"],
            "png_mask":      png_mask,
        })

    # ── Elegir el mejor match entre todos los templates ───────────────────────
    best       = _best_eco_match(png_mask, match_results)
    match_col  = best["col"]
    match_row  = best["row"]
    score      = best["score"]
    method     = best["method"]
    eco_mask   = best["eco_mask"]
    eco_transform = best["eco_transform"]
    ref_crs    = best["eco_crs"]
    eco_w      = best["eco_w"]
    eco_h      = best["eco_h"]

    logger.info("Match final: (%d,%d) score=%.4f method=%s template=%s",
                match_col, match_row, score, method, best["template"])

    if score < MIN_MATCH_SCORE:
        logger.warning("Score bajo (%.4f < %.4f). Match puede ser incorrecto.",
                       score, MIN_MATCH_SCORE)

    # ── 4. Refinamiento subpíxel y cálculo directo de la georreferenciación ───
    pixel_size_x = eco_transform.a
    pixel_size_y = eco_transform.e

    # Refinar (match_col, match_row) con precisión decimal (subpíxel)
    image_f = png_mask.astype(np.float32)
    template_f = eco_mask.astype(np.float32)
    try:
        res_map = cv2.matchTemplate(image_f, template_f, cv2.TM_CCOEFF_NORMED)
        sub_col, sub_row = refine_subpixel_peak(res_map, match_col, match_row)
    except Exception:
        sub_col, sub_row = float(match_col), float(match_row)

    logger.info("Posición entera: (%d,%d) -> Subpíxel: (%.3f, %.3f)",
                match_col, match_row, sub_col, sub_row)

    # Centro geográfico del eco en el template (Ground Truth real)
    true_lon, true_lat = get_center_geo(eco_transform, eco_w, eco_h)

    # Centro en píxeles del eco dentro de la imagen completa (con precisión decimal)
    eco_center_col = sub_col + (eco_w - 1) / 2.0
    eco_center_row = sub_row + (eco_h - 1) / 2.0

    # Proyección directa hacia la esquina superior izquierda (origen 0,0)
    origin_lon = true_lon - (eco_center_col * pixel_size_x)
    origin_lat = true_lat - (eco_center_row * pixel_size_y)

    corrected_transform = Affine(pixel_size_x, 0.0, origin_lon, 0.0, pixel_size_y, origin_lat)
    delta_lon = 0.0
    delta_lat = 0.0
    logger.info("Transform calculado (subpíxel): %s | CRS: %s", corrected_transform, ref_crs)

    # ── 5. Máscara de clutter por forma exacta del eco ───────────────────────
    # Se usa la forma exacta del template (eco_mask > 0), NO un rectángulo
    # con margen, para no eliminar precipitación real que pase sobre el eco.
    clutter_mask = np.zeros((height, width), dtype=bool)
    match_row_int = int(round(match_row))
    match_col_int = int(round(match_col))
    row_end = min(match_row_int + eco_h, height)
    col_end = min(match_col_int + eco_w, width)
    clutter_mask[match_row_int:row_end, match_col_int:col_end] = (
        eco_mask[:row_end - match_row_int, :col_end - match_col_int] > 0
    )
    logger.info("clutter_mask: %d px de eco fijo enmascarados",
                int(np.count_nonzero(clutter_mask)))

    # ── 6. Aplicar filtros al dbz_map y convertir a uint8 ────────────────────
    export_dbz = _apply_dbz_filters(dbz_map, clutter_mask)

    # Verificar que solo tenemos valores válidos
    unique_values = set(np.unique(export_dbz))
    valid_values = {0, 10, 20, 30, 35, 36, 39, 42, 45, 48, 51, 54, 57, 60, 65, 70, 80}
    invalid = unique_values - valid_values
    if invalid:
        logger.warning("Valores dBZ inesperados en export: %s", invalid)

    logger.info("dBZ exportado: valores únicos = %s", sorted(unique_values & valid_values))
    logger.info("dBZ exportado: %d px con datos, %d px NoData",
                int(np.count_nonzero(export_dbz)), int(np.count_nonzero(export_dbz == 0)))

    # ── 7. GeoTIFF final en memoria (1 banda dBZ uint8 + Color Table) ────────
    etiquetas = {
        "GEO_METODO": "legado",
        "GEO_VARIANTE": "ninguna",
        "GEO_ESTADO": "legado_sin_calibrar",
        "GEO_TEMPLATE": str(best["template"]),
    }
    geotiff_bytes = dbz_array_to_geotiff_bytes(export_dbz, corrected_transform, ref_crs,
                                               etiquetas_geo=etiquetas)
    logger.info("GeoTIFF exportado: %d bytes (1 banda dBZ uint8 + Color Table, NoData=0)", len(geotiff_bytes))

    return GeoResultado(
        geotiff_bytes=geotiff_bytes,
        transform_affine=str(corrected_transform),
        crs_str=str(ref_crs),
        score_match=score,
        delta_lon=delta_lon,
        delta_lat=delta_lat,
        clutter_mask=clutter_mask,
        dbz_array=export_dbz,
        estado_geo="legado_sin_calibrar",
        umbral_dbz=10,
    )

# ══════════════════════════════════════════════════════════════════════════════
# Geolocalización robusta (desde 15/10/2026) — ver informe GEO_ROBUSTO
# ══════════════════════════════════════════════════════════════════════════════

NOMBRE_GEOMETRIAS = "geometrias_gif.json"
NOMBRES_TEMPLATES_ECO = ("template_eco_fijo.tif", "template_eco_fijo2.tif")

VERSION_GEO = "geo_robusto_v1"
UMBRAL_DBZ_MATCH: int = 35        # clutter fuerte; deja afuera la lluvia estratiforme
UMBRAL_DBZ_RESPALDO: int = 10     # si la forma fuerte del template no alcanza
MIN_PX_MASCARA: int = 150         # por debajo, la forma no es reconocible
VENTANA_PX: int = 25              # ~18 km; cubre de sobra el jitter de recorte
TOL_TEMPLATES_PX: float = 4.0     # σ de cada template en 45 frames intactos <= 2,7 px
RUIDO_PX: float = 3.0             # corrimiento menor = ruido del matching
SCORE_MIN: float = 0.10           # el eco es ralo: mediana del score ~0,2
TOL_COLOR_TEMPLATE: float = 30.0  # distancia RGB máx. para asignar dBZ al template
CRS_SALIDA: str | None = "EPSG:3857"  # D1 pendiente: None = AEQD nativo, sin remuestreo


# ── Capa 0: geometría calibrada por variante ──────────────────────────────────

@dataclass(frozen=True)
class Geometria:
    """Geometría de una variante de GIF (un tamaño de recorte de crop_imagen).

    pixel_m     tamaño de píxel sobre el terreno (m), cuadrado.
    c0, r0      columna/fila (centro de píxel) del 0 km = el radar.
    lat0, lon0  centro de la proyección AEQD.
    ecos        esquina sup. izq. (col, fila) de cada template en esta variante,
                en PÍXELES. Su georreferencia propia ya no se usa.
    """
    nombre: str
    ancho: int
    alto: int
    pixel_m: float
    c0: float
    r0: float
    lat0: float
    lon0: float
    ecos: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def crs(self) -> CRS:
        return CRS.from_proj4(
            f"+proj=aeqd +lat_0={self.lat0} +lon_0={self.lon0} "
            "+datum=WGS84 +units=m +no_defs"
        )

    def transform(self, dc: float = 0.0, dr: float = 0.0) -> Affine:
        """Affine de la imagen, corrida (dc, dr) px respecto de la variante.

        x(c) = x0 + s·c ; y(r) = y0 − s·r, con x0 = −(c0+½)s, y0 = (r0+½)s.
        El ½ aparece porque el transform apunta a la ESQUINA del píxel y los
        rótulos de los ejes marcan su CENTRO.
        Si los ecos aparecen corridos (dc, dr): x0' = x0 − dc·s ; y0' = y0 + dr·s.
        """
        s = self.pixel_m
        x0 = -(self.c0 + 0.5) * s - dc * s
        y0 = (self.r0 + 0.5) * s + dr * s
        return Affine(s, 0.0, x0, 0.0, -s, y0)


def cargar_geometrias(ruta: Path | str | None = None) -> dict[str, Geometria]:
    """Lee templates/geometrias_gif.json → {nombre: Geometria}. {} si no existe."""
    ruta = Path(ruta) if ruta is not None else Path(settings.template_dir) / NOMBRE_GEOMETRIAS
    if not ruta.exists():
        logger.warning("No existe %s: todas las imágenes irán por el método legado", ruta)
        return {}
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    geos: dict[str, Geometria] = {}
    for nombre, g in datos["variantes"].items():
        geos[nombre] = Geometria(
            nombre=nombre,
            ancho=int(g["ancho"]),
            alto=int(g["alto"]),
            pixel_m=float(g["pixel_m"]),
            c0=float(g["cero_km_px"][0]),
            r0=float(g["cero_km_px"][1]),
            lat0=float(g["centro_aeqd"]["lat"]),
            lon0=float(g["centro_aeqd"]["lon"]),
            ecos={k: (int(v[0]), int(v[1])) for k, v in g["ecos_px"].items()},
        )
    return geos


def elegir_geometria(shape: tuple[int, ...], geometrias: dict[str, Geometria]) -> Geometria | None:
    """Variante cuyo tamaño coincide EXACTO con la imagen; None si no hay.

    Exacto a propósito: otro tamaño es otro recorte y su geometría no aplica.
    Mejor marcar la imagen que georreferenciarla mal.
    """
    alto, ancho = shape[:2]
    for g in geometrias.values():
        if g.ancho == ancho and g.alto == alto:
            return g
    return None


# ── Capa 1: máscaras en dBZ (solo ecos fuertes) ───────────────────────────────

def mascara_dbz(dbz: np.ndarray, umbral: int) -> np.ndarray:
    """uint8 0/255 con los píxeles >= umbral dBZ."""
    return ((dbz >= umbral).astype(np.uint8)) * 255


def template_a_dbz(rgb: np.ndarray, tol: float = TOL_COLOR_TEMPLATE) -> np.ndarray:
    """RGB de un template → dBZ por color más cercano de DBZ_COLOR_MAP.

    Los templates son recortes de GIFs reales: el antialiasing que queda lejos
    de todo color de la paleta (> tol) se descarta (0).
    """
    rgb = rgb[:, :, :3].astype(np.float32)
    niveles = np.array(list(DBZ_COLOR_MAP.keys()), dtype=np.int32)
    colores = np.array(list(DBZ_COLOR_MAP.values()), dtype=np.float32)
    dist = np.linalg.norm(rgb[:, :, None, :] - colores[None, None, :, :], axis=3)
    idx = dist.argmin(axis=2)
    cerca = dist.min(axis=2) <= tol
    no_negro = rgb.max(axis=2) > 10
    return np.where(cerca & no_negro, niveles[idx], 0).astype(np.uint8)


def elegir_umbral(dbz_template: np.ndarray) -> int:
    """35 dBZ si la forma fuerte del template es reconocible; si no, 10."""
    if int(np.count_nonzero(dbz_template >= UMBRAL_DBZ_MATCH)) >= MIN_PX_MASCARA:
        return UMBRAL_DBZ_MATCH
    return UMBRAL_DBZ_RESPALDO


@dataclass
class TemplateEco:
    nombre: str
    dbz: np.ndarray        # (h, w) uint8, dBZ del template
    umbral: int            # 35 o 10
    mascara: np.ndarray    # (h, w) uint8 0/255 a ese umbral
    forma: np.ndarray      # (h, w) bool, forma completa (para borrar el clutter)


def cargar_templates(dir_templates: Path | str | None = None) -> list[TemplateEco]:
    """Lee los templates de eco fijo en su resolución NATIVA (sin reescalar).

    Su georreferencia se ignora: lo que estaba mal era la etiqueta geográfica,
    no la forma. La posición la da la variante, en píxeles.
    """
    dir_templates = Path(dir_templates) if dir_templates is not None else Path(settings.template_dir)
    templates: list[TemplateEco] = []
    for nombre in NOMBRES_TEMPLATES_ECO:
        ruta = dir_templates / nombre
        if not ruta.exists():
            continue
        with rasterio.open(ruta) as src:
            rgb = np.moveaxis(src.read(), 0, -1)
        dbz = template_a_dbz(rgb)
        umbral = elegir_umbral(dbz)
        templates.append(TemplateEco(nombre=nombre, dbz=dbz, umbral=umbral,
                                     mascara=mascara_dbz(dbz, umbral), forma=dbz > 0))
    if not templates:
        raise FileNotFoundError(f"No hay templates de eco fijo en {dir_templates}")
    return templates


@lru_cache(maxsize=4)
def _geometrias_cache(template_dir: str) -> dict[str, Geometria]:
    """Geometrías calibradas, leídas una vez por proceso."""
    return cargar_geometrias(Path(template_dir) / NOMBRE_GEOMETRIAS)


@lru_cache(maxsize=4)
def _templates_cache(template_dir: str) -> tuple[TemplateEco, ...]:
    """Templates de eco fijo en dBZ, leídos una vez por proceso."""
    return tuple(cargar_templates(template_dir))


# ── Capa 2: búsqueda en ventana ───────────────────────────────────────────────

@dataclass(frozen=True)
class Match:
    col: int
    row: int
    score: float

    def corrimiento(self, esperado: tuple[int, int]) -> tuple[int, int]:
        return self.col - esperado[0], self.row - esperado[1]


def _recorte_con_relleno(img: np.ndarray, r0: int, c0: int, alto: int, ancho: int) -> np.ndarray:
    """img[r0:r0+alto, c0:c0+ancho] rellenando con 0 lo que cae afuera."""
    out = np.zeros((alto, ancho), dtype=img.dtype)
    ih, iw = img.shape[:2]
    rr0, cc0 = max(r0, 0), max(c0, 0)
    rr1, cc1 = min(r0 + alto, ih), min(c0 + ancho, iw)
    if rr1 > rr0 and cc1 > cc0:
        out[rr0 - r0:rr1 - r0, cc0 - c0:cc1 - c0] = img[rr0:rr1, cc0:cc1]
    return out


def buscar_en_ventana(
    mascara_img: np.ndarray,
    mascara_tmpl: np.ndarray,
    esperado: tuple[int, int],
    ventana: int = VENTANA_PX,
) -> Match | None:
    """Template matching SOLO a ±ventana px de la posición esperada (col, fila).

    Un señuelo a 150 km (la lluvia de San Rafael del 13/10) no puede ganar
    porque ni siquiera se mira. Score: TM_CCOEFF_NORMED sobre máscaras binarias.
    None si no hay nada que comparar.
    """
    h, w = mascara_tmpl.shape
    col_e, row_e = esperado
    region = _recorte_con_relleno(mascara_img, row_e - ventana, col_e - ventana,
                                  h + 2 * ventana, w + 2 * ventana)
    if not region.any() or not mascara_tmpl.any():
        return None
    res = cv2.matchTemplate(region.astype(np.float32), mascara_tmpl.astype(np.float32),
                            cv2.TM_CCOEFF_NORMED)
    res[~np.isfinite(res)] = -1.0
    _, score, _, (cx, cy) = cv2.minMaxLoc(res)
    return Match(col=col_e - ventana + cx, row=row_e - ventana + cy, score=float(score))


# ── Capa 4: dos templates como testigos ───────────────────────────────────────

def combinar_corrimientos(
    corrimientos: list[tuple[tuple[int, int], float] | None],
    tol: float = TOL_TEMPLATES_PX,
    score_min: float = SCORE_MIN,
) -> tuple[str, tuple[float, float]]:
    """Combina los corrimientos [((dc, dr), score) | None] de cada template.

      "consistente"    dos testigos válidos que coinciden a ±tol → promedio
      "inconsistente"  dos testigos válidos que no coinciden     → (0, 0)
      "un_template"    un solo testigo válido                    → el suyo
      "sin_match"      ninguno                                   → (0, 0)
    """
    validos = [c for c in corrimientos if c is not None and c[1] >= score_min]
    if not validos:
        return "sin_match", (0.0, 0.0)
    if len(validos) == 1:
        (dc, dr), _ = validos[0]
        return "un_template", (float(dc), float(dr))
    (dc1, dr1), _ = validos[0]
    (dc2, dr2), _ = validos[1]
    if abs(dc1 - dc2) <= tol and abs(dr1 - dr2) <= tol:
        return "consistente", ((dc1 + dc2) / 2.0, (dr1 + dr2) / 2.0)
    return "inconsistente", (0.0, 0.0)


# ── Capas 3+5: nominal salvo dos testigos ─────────────────────────────────────

def decidir_corrimiento(
    estado: str,
    corrimiento: tuple[float, float],
    ruido: float = RUIDO_PX,
) -> tuple[str, tuple[float, float]]:
    """Mueve la imagen SOLO con dos testigos consistentes y más allá del ruido.

    Reemplaza a la capa 5 (historial temporal): con la geometría calibrada el
    corrimiento esperado del scheduler es (0, 0), y el banco no es una serie
    temporal. Ante la duda, geometría nominal (KISS, sin estado persistente).
    """
    if estado == "consistente" and math.hypot(*corrimiento) > ruido:
        return "corregido", corrimiento
    return f"nominal_{estado}", (0.0, 0.0)


def estimar_corrimiento(
    dbz_map: np.ndarray,
    templates: list[TemplateEco] | tuple[TemplateEco, ...],
    geometria: Geometria,
) -> tuple[str, tuple[float, float], float, int]:
    """Capas 1→2→4→3+5. Devuelve (estado_geo, corrimiento, score, umbral)."""
    testigos: list[tuple[tuple[int, int], float] | None] = []
    scores: list[float] = []
    umbral_usado = UMBRAL_DBZ_MATCH
    for t in templates:
        if t.nombre not in geometria.ecos:
            testigos.append(None)
            continue
        esperado = geometria.ecos[t.nombre]
        umbral_usado = min(umbral_usado, t.umbral)
        m = buscar_en_ventana(mascara_dbz(dbz_map, t.umbral), t.mascara, esperado)
        if m is None:
            testigos.append(None)
            continue
        testigos.append((m.corrimiento(esperado), m.score))
        scores.append(m.score)
        logger.info("  [%s] match (%d,%d) score=%.3f corrimiento=%s",
                    t.nombre, m.col, m.row, m.score, m.corrimiento(esperado))
    estado, corr = combinar_corrimientos(testigos)
    estado_geo, corr_final = decidir_corrimiento(estado, corr)
    return estado_geo, corr_final, (max(scores) if scores else 0.0), umbral_usado


# ── Clutter en posición real y reproyección ───────────────────────────────────

def _pegar_forma(shape: tuple[int, int], forma: np.ndarray, r0: int, c0: int) -> np.ndarray:
    """Pega `forma` (h, w) en un lienzo bool `shape` con esquina en (r0, c0)."""
    h, w = forma.shape
    lienzo = np.zeros(shape, dtype=bool)
    ih, iw = shape
    rr0, cc0 = max(r0, 0), max(c0, 0)
    rr1, cc1 = min(r0 + h, ih), min(c0 + w, iw)
    if rr1 > rr0 and cc1 > cc0:
        lienzo[rr0:rr1, cc0:cc1] = forma[rr0 - r0:rr1 - r0, cc0 - c0:cc1 - c0]
    return lienzo


def mascara_clutter(
    shape: tuple[int, ...],
    templates: list[TemplateEco] | tuple[TemplateEco, ...],
    geometria: Geometria,
    corrimiento: tuple[float, float],
) -> np.ndarray:
    """bool (H, W): forma de los templates en su posición REAL
    (nominal de la variante + corrimiento final), NO donde cayó el match.
    Así, si el match se engaña, no se borra lluvia real.
    """
    mask = np.zeros(shape[:2], dtype=bool)
    dc, dr = int(round(corrimiento[0])), int(round(corrimiento[1]))
    for t in templates:
        if t.nombre in geometria.ecos:
            col, row = geometria.ecos[t.nombre]
            mask |= _pegar_forma(shape[:2], t.forma, row + dr, col + dc)
    return mask


def reproyectar(
    dbz: np.ndarray,
    transform: Affine,
    crs_origen: CRS,
    crs_salida: str | None = CRS_SALIDA,
) -> tuple[np.ndarray, Affine, CRS]:
    """AEQD → crs_salida por VECINO MÁS CERCANO.

    Los dBZ son categorías: un bilineal inventaría niveles que la paleta no
    tiene. Con crs_salida=None se devuelve el raster nativo (AEQD).
    """
    if crs_salida is None:
        return dbz, transform, crs_origen
    alto, ancho = dbz.shape
    destino = CRS.from_user_input(crs_salida)
    izq, arr = transform * (0, 0)
    der, aba = transform * (ancho, alto)
    t_out, w_out, h_out = calculate_default_transform(
        crs_origen, destino, ancho, alto, left=izq, bottom=aba, right=der, top=arr)
    out = np.zeros((h_out, w_out), dtype=np.uint8)
    reproject(source=dbz, destination=out,
              src_transform=transform, src_crs=crs_origen,
              dst_transform=t_out, dst_crs=destino,
              resampling=Resampling.nearest, src_nodata=0, dst_nodata=0)
    return out, t_out, destino


# ── API pública ───────────────────────────────────────────────────────────────

def geolocalizar(
    filled_rgb: np.ndarray,
    dbz_map: np.ndarray,
    *,
    geometrias: dict[str, Geometria] | None = None,
    templates: list[TemplateEco] | None = None,
    crs_salida: str | None = CRS_SALIDA,
) -> GeoResultado:
    """Pipeline de geolocalización (Fase 6).

    1. Elegir la variante calibrada por tamaño exacto. Si no hay → legado marcado.
    2. Estimar el corrimiento con los dos templates (ventana, >=35 dBZ, testigos).
    3. Borrar el clutter en su posición real y aplicar los filtros de siempre.
    4. Transform AEQD de la variante (+ corrimiento) y reproyectar a crs_salida.
    5. GeoTIFF 1 banda dBZ + Color Table + etiquetas GEO_*.

    Args:
        filled_rgb: (H, W, 3) uint8, imagen post-relleno. Solo la usa el
            camino legado (máscara de forma para el matching en cascada).
        dbz_map: (H, W) int, dBZ de cada píxel post-relleno (0 = sin eco).
        geometrias, templates: inyectables para tests; por defecto se leen de
            settings.template_dir (una sola vez por proceso).
        crs_salida: "EPSG:3857" (default) o None para AEQD nativo.
    """
    if geometrias is None:
        geometrias = _geometrias_cache(str(settings.template_dir))
    geometria = elegir_geometria(dbz_map.shape, geometrias)
    if geometria is None:
        logger.warning("Geo: tamaño %s sin variante calibrada → legado_sin_calibrar",
                       dbz_map.shape[:2])
        return _geolocalizar_legado(filled_rgb, dbz_map)

    if templates is None:
        templates = list(_templates_cache(str(settings.template_dir)))

    estado_geo, corr, score, umbral = estimar_corrimiento(dbz_map, templates, geometria)
    logger.info("Geo robusta: variante=%s estado=%s corrimiento=%s score=%.3f",
                geometria.nombre, estado_geo, corr, score)

    clutter = mascara_clutter(dbz_map.shape, templates, geometria, corr)
    export = _apply_dbz_filters(dbz_map, clutter)

    dbz_out, t_out, crs_out = reproyectar(export, geometria.transform(*corr),
                                          geometria.crs, crs_salida)
    etiquetas = {
        "GEO_METODO": VERSION_GEO,
        "GEO_VARIANTE": geometria.nombre,
        "GEO_ESTADO": estado_geo,
        "GEO_CORRIMIENTO_PX": f"{corr[0]:+.1f},{corr[1]:+.1f}",
        "GEO_UMBRAL_DBZ": str(umbral),
        "GEO_CRS_NATIVO": geometria.crs.to_proj4(),
    }
    return GeoResultado(
        geotiff_bytes=dbz_array_to_geotiff_bytes(dbz_out, t_out, crs_out, etiquetas_geo=etiquetas),
        transform_affine=str(t_out),
        crs_str=str(crs_out),
        score_match=score,
        delta_lon=0.0,
        delta_lat=0.0,
        clutter_mask=clutter,      # grilla de ENTRADA (la usa _calcular_metricas)
        dbz_array=dbz_out,         # grilla de SALIDA (la del GeoTIFF)
        estado_geo=estado_geo,
        corrimiento_px=corr,
        variante=geometria.nombre,
        umbral_dbz=umbral,
    )
