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

MIN_MATCH_SCORE_GLOBAL: float = 0.50
MIN_SHAPE_IOU: float = 0.20
MIN_GLOBAL_CORR: float = 0.30
ANCHOS = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00]

# Filtro DBZ < 35
DBZ_COLOR_MAP = {
    10: (66, 63, 140),  20: (0, 88, 5),    30: (0, 111, 9),
    35: (0, 132, 220),  36: (0, 82, 233),   39: (108, 39, 199),
    42: (210, 30, 133), 45: (200, 102, 135), 48: (219, 136, 52),
    51: (255, 195, 41), 54: (255, 247, 10),  57: (255, 155, 83),
    60: (255, 95, 0),   65: (255, 52, 0),    70: (191, 191, 191),
    80: (212, 212, 212),
}
DBZ_BELOW_35 = {k: v for k, v in DBZ_COLOR_MAP.items() if k < 35}
DBZ_COLOR_TOLERANCE: float = 18

# Filtro marca de agua / verde
WATERMARK_GREEN_MIN: int = 50
WATERMARK_GREEN_MAX: int = 140
WATERMARK_DOMINANCE: int = 15


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_template_paths(width: int) -> tuple[Path, Path]:
    """
    Devuelve (template_geo, template_eco_fijo_principal) según el ancho.
    El segundo valor es solo el primer eco template; para obtener todos
    los templates eco usa get_eco_template_paths().
    """
    template_dir = Path(settings.template_dir)
    geo_name = "tif800.tif" if width > THRESHOLD_WIDTH else "tif700.tif"
    geo_path = template_dir / geo_name

    if not geo_path.exists():
        raise FileNotFoundError(f"Template de georreferencia no encontrado: {geo_path}")

    return geo_path, _get_eco_template_paths(template_dir)[0]


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


# ── Filtros de salida ─────────────────────────────────────────────────────────

def build_dbz_below35_mask(arr: np.ndarray) -> np.ndarray:
    """
    Devuelve máscara booleana de píxeles con color correspondiente a dBZ < 35.
    Estos son ecos débiles que no representan precipitación significativa.
    """
    rgb = arr[:, :, :3].astype(np.float32)
    mask = np.zeros(arr.shape[:2], dtype=bool)
    for _, (r, g, b) in DBZ_BELOW_35.items():
        dist = np.linalg.norm(rgb - np.array([r, g, b], dtype=np.float32), axis=2)
        mask |= dist <= DBZ_COLOR_TOLERANCE
    logger.debug("  Filtro DBZ<35: %d píxeles", int(np.count_nonzero(mask)))
    return mask


def build_watermark_mask(arr: np.ndarray) -> np.ndarray:
    """
    Devuelve máscara booleana de píxeles verdes que corresponden a la marca
    de agua / precipitación débil umbralada (verde dominante en rango fijo).
    """
    rgb = arr[:, :, :3].astype(np.int16)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    mask = (
        (g > r + WATERMARK_DOMINANCE) &
        (g > b + WATERMARK_DOMINANCE) &
        (g >= WATERMARK_GREEN_MIN) &
        (g <= WATERMARK_GREEN_MAX)
    )
    logger.debug("  Filtro marca de agua: %d píxeles", int(np.count_nonzero(mask)))
    return mask


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
    th, tw = template_mask.shape[:2]
    region = _extract_region(image_mask, top_left, th, tw)
    a, b = region == 255, template_mask == 255
    union = np.logical_or(a, b).sum()
    iou = float(np.logical_and(a, b).sum()) / float(union) if union > 0 else 0.0
    return iou, iou >= MIN_SHAPE_IOU


def verify_corr(image_mask: np.ndarray, template_mask: np.ndarray,
                top_left: tuple) -> tuple[float, bool]:
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


def _scan_zone(result_map: np.ndarray, image_mask: np.ndarray,
               template_mask: np.ndarray, zone_width: float,
               label: str, strict: bool = True):
    """
    Escanea izquierda→derecha hasta zone_width.
    strict=True: exige IoU+Corr válidos.
    strict=False: devuelve el mejor score sin verificar forma.
    """
    safe = result_map.copy()
    safe[~np.isfinite(safe)] = -1.0
    ih, iw = image_mask.shape
    th, tw = template_mask.shape[:2]
    n_cols = safe.shape[1]
    max_col = max(1, int(n_cols * zone_width))
    min_overlap = max(int(th * tw * 0.05), 10)

    if not strict:
        zone = safe[:, :max_col]
        idx = int(np.argmax(zone))
        row, col = idx // zone.shape[1], idx % zone.shape[1]
        score = float(zone[row, col])
        return ((col, row), score, f"{label}_raw") if score >= 0 else None

    for col in range(max_col):
        best_row = int(np.argmax(safe[:, col]))
        score = float(safe[best_row, col])
        if score < MIN_MATCH_SCORE:
            continue
        r1 = min(best_row + th, ih)
        c1 = min(col + tw, iw)
        if np.count_nonzero(image_mask[best_row:r1, col:c1]) < min_overlap:
            continue
        top_left = (col, best_row)
        iou, iou_ok = verify_iou(image_mask, template_mask, top_left)
        corr, corr_ok = verify_corr(image_mask, template_mask, top_left)
        if iou_ok and corr_ok:
            logger.info("    [%s z=%.2f] score=%.4f @ (%d,%d)", label, zone_width, score, col, best_row)
            return top_left, score, f"{label}_z{int(zone_width*100)}"
    return None


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


def array_to_geotiff_bytes(
    arr: np.ndarray,
    transform: Affine,
    crs: object,
    compress: str = COMPRESS,
    nodata: int | None = 0,
) -> bytes:
    """Convierte un array numpy a bytes de GeoTIFF en memoria (sin escribir a disco)."""
    if arr.ndim == 3:
        height, width, count = arr.shape
        bands = [arr[:, :, i] for i in range(count)]
    else:
        height, width = arr.shape
        count = 1
        bands = [arr]

    buffer = io.BytesIO()
    with rasterio.open(
        buffer, "w", driver="GTiff",
        height=height, width=width, count=count,
        dtype=arr.dtype, crs=crs, transform=transform,
        compress=compress, nodata=nodata,
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
        "clutter_mask",
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
    4. Cargar todos los templates eco disponibles (eco fijo 1 y 2).
    5. Template matching en cascada (masked → classic) con verificación
       de forma (IoU + Corr) por ancho incremental. Se corre para cada
       template eco y se elige el mejor match.
    6. Calcular delta geográfico entre posición encontrada y real.
    7. Corregir el Affine Transform.
    8. Construir máscara booleana de clutter (ecos fijos) por forma exacta,
       sin margen rectangular para no eliminar tormenta real adyacente.
    9. Aplicar filtros al array de salida:
       - Poner a 0 los píxeles de eco fijo (clutter_mask, forma exacta).
       - Poner a 0 los píxeles con color de dBZ < 35.
       - Poner a 0 los píxeles con color verde de marca de agua.
    10. Generar GeoTIFF final en memoria (BytesIO).

    Args:
        filled_rgb: Array (H, W, 3) uint8. Imagen post-relleno de huecos.

    Returns:
        GeoResultado con los bytes del GeoTIFF limpio, metadatos de
        geolocalización y clutter_mask (máscara booleana H×W de la zona de
        ecos fijos, útil para excluir del cálculo de dbz_max).

    Raises:
        FileNotFoundError: Si los templates no están en template_dir.
        ValueError: Si todos los templates eco son más grandes que la imagen.
        RuntimeError: Si todos los métodos de template matching fallan.
    """
    height, width = filled_rgb.shape[:2]
    template_dir = Path(settings.template_dir)

    # ── 1. Template de georreferencia ─────────────────────────────────────────
    geo_name = "tif800.tif" if width > THRESHOLD_WIDTH else "tif700.tif"
    geo_path = template_dir / geo_name
    if not geo_path.exists():
        raise FileNotFoundError(f"Template de georreferencia no encontrado: {geo_path}")
    logger.info("Template geo: %s", geo_path.name)

    # ── 2. CRS y Transform de referencia ─────────────────────────────────────
    with rasterio.open(geo_path) as src_geo:
        ref_transform = src_geo.transform
        ref_crs = src_geo.crs
    logger.info("CRS: %s | Transform: %s", ref_crs, ref_transform)

    # ── 3. Máscara de forma del array de entrada ──────────────────────────────
    png_mask = extract_shape_mask(filled_rgb)

    # ── 4. Cargar todos los templates eco ────────────────────────────────────
    eco_paths = _get_eco_template_paths(template_dir)
    logger.info("Templates eco: %s", [p.name for p in eco_paths])

    eco_data = []
    for eco_path in eco_paths:
        with rasterio.open(eco_path) as src_eco:
            eco_arr       = np.moveaxis(src_eco.read(), 0, -1)  # (C,H,W)→(H,W,C)
            eco_transform = src_eco.transform
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
            "eco_w":         eco_w,
            "eco_h":         eco_h_px,
        })
        logger.info("[%s] mask: %d px activos", eco_path.name, int(np.count_nonzero(eco_mask)))

    if not eco_data:
        raise ValueError("Ningún template eco es compatible con esta imagen (todos más grandes).")

    # ── 5. Template matching para cada template eco ───────────────────────────
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
            "eco_w":         eco["eco_w"],
            "eco_h":         eco["eco_h"],
            "png_mask":      png_mask,
        })

    # ── Elegir el mejor match entre todos los templates ───────────────────────
    best       = _best_eco_match(png_mask, match_results)
    match_col  = best["col"]
    match_row  = best["row"]
    top_left   = (match_col, match_row)
    score      = best["score"]
    method     = best["method"]
    eco_mask   = best["eco_mask"]
    eco_transform = best["eco_transform"]
    eco_w      = best["eco_w"]
    eco_h      = best["eco_h"]

    logger.info("Match final: (%d,%d) score=%.4f method=%s template=%s",
                match_col, match_row, score, method, best["template"])

    if score < MIN_MATCH_SCORE:
        logger.warning("Score bajo (%.4f < %.4f). Match puede ser incorrecto.",
                       score, MIN_MATCH_SCORE)

    unreliable = "unreliable" in method or method == "fallback"

    # ── 6. Delta geográfico ───────────────────────────────────────────────────
    if unreliable:
        logger.warning("Fallback no confiable. Sin corrección geográfica.")
        corrected_transform = ref_transform
        delta_lon = 0.0
        delta_lat = 0.0
    else:
        eco_center_col = match_col + (eco_w - 1) / 2.0
        eco_center_row = match_row + (eco_h - 1) / 2.0
        found_lon, found_lat = pixel_to_geo(ref_transform, eco_center_col, eco_center_row)
        true_lon, true_lat   = get_center_geo(eco_transform, eco_w, eco_h)
        delta_lon = true_lon - found_lon
        delta_lat = true_lat - found_lat
        logger.info("Δlon=%.6f, Δlat=%.6f", delta_lon, delta_lat)

        # ── 7. Corregir Transform ─────────────────────────────────────────────
        corrected_transform = correct_transform(ref_transform, delta_lon, delta_lat)

    # ── 8. Máscara de clutter por forma exacta del eco ───────────────────────
    # Se usa la forma exacta del template (eco_mask > 0), NO un rectángulo
    # con margen, para no eliminar precipitación real que pase sobre el eco.
    clutter_mask = np.zeros((height, width), dtype=bool)
    row_end = min(match_row + eco_h, height)
    col_end = min(match_col + eco_w, width)
    clutter_mask[match_row:row_end, match_col:col_end] = (
        eco_mask[:row_end - match_row, :col_end - match_col] > 0
    )
    logger.info("clutter_mask: %d px de eco fijo enmascarados",
                int(np.count_nonzero(clutter_mask)))

    # ── 9. Filtros de salida ──────────────────────────────────────────────────
    export_rgb = filled_rgb.copy()

    # 9a. Eco fijo (forma exacta — sin margen rectangular)
    export_rgb[clutter_mask] = 0

    # 9b. dBZ < 35 (precipitación muy débil / ruido cromático)
    export_rgb[build_dbz_below35_mask(export_rgb)] = 0

    # 9c. Verdes de marca de agua / umbral de precipitación débil
    export_rgb[build_watermark_mask(export_rgb)] = 0

    logger.info("Filtros aplicados: eco_fijo + dBZ<35 + marca_agua")

    # ── 10. GeoTIFF final en memoria ──────────────────────────────────────────
    geotiff_bytes = array_to_geotiff_bytes(export_rgb, corrected_transform, ref_crs)
    logger.info("GeoTIFF exportado (ecos fijos + dbz<35 + watermark → NoData=0)")

    return GeoResultado(
        geotiff_bytes=geotiff_bytes,
        transform_affine=str(corrected_transform),
        crs_str=str(ref_crs),
        score_match=score,
        delta_lon=delta_lon,
        delta_lat=delta_lat,
        clutter_mask=clutter_mask,
    )