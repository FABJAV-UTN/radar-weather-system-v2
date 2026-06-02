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

# Caos cromático
COLOR_CANDIDATES: int = 10    # top-N candidatos de forma que se validan por color
MIN_UNIQUE_COLORS: int = 30   # colores únicos mínimos esperados en el eco fijo
COLOR_CHAOS_WEIGHT: float = 0.7  # peso del caos en score combinado (forma=0.3, caos=0.7)


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


def _valid_score(score: float) -> bool:
    """Devuelve True solo si el score es un número finito y no negativo."""
    return np.isfinite(score) and score >= 0.0


def _best_loc_from_result(
    result_map: np.ndarray,
    image_mask: np.ndarray,
    tmpl_h: int,
    tmpl_w: int,
    min_overlap_ratio: float = 0.05,
) -> tuple[tuple, float]:
    """
    Elige la mejor posición en el mapa de correlación excluyendo zonas vacías.

    TM_CCORR_NORMED con máscara produce inf/nan cuando la región de la imagen
    bajo la máscara tiene norma cero (zona completamente negra). Para evitar
    que esos valores inválidos "ganen" la selección, se descarta cualquier
    posición candidata que no tenga suficientes píxeles de forma en la ventana.

    Estrategia:
        1. Marcar como -1 todas las posiciones con valor no finito.
        2. Recorrer los mejores candidatos (hasta MAX_CANDIDATES) en orden
           descendente de score.
        3. Para cada candidato, calcular cuántos píxeles de forma (image_mask==255)
           caen dentro de la ventana del template.
        4. Aceptar el primero que supere min_overlap_ratio * template_area.
        5. Si ninguno supera el umbral, devolver el candidato con mayor score
           finito (puede ser bajo, pero al menos es numérico).
    """
    MAX_CANDIDATES = 20
    tmpl_area = tmpl_h * tmpl_w

    safe_map = result_map.copy()
    safe_map[~np.isfinite(safe_map)] = -1.0

    flat = safe_map.flatten()
    top_indices = np.argpartition(flat, -MAX_CANDIDATES)[-MAX_CANDIDATES:]
    top_indices = top_indices[np.argsort(flat[top_indices])[::-1]]

    img_h, img_w = image_mask.shape
    best_finite_loc = None
    best_finite_score = -1.0

    for idx in top_indices:
        score = float(flat[idx])
        if score < 0:
            continue

        row = int(idx // safe_map.shape[1])
        col = int(idx % safe_map.shape[1])

        r0, r1 = row, min(row + tmpl_h, img_h)
        c0, c1 = col, min(col + tmpl_w, img_w)
        window = image_mask[r0:r1, c0:c1]
        ratio = int(np.count_nonzero(window)) / tmpl_area

        logger.debug("      candidato (%d,%d) score=%.4f overlap=%.3f", col, row, score, ratio)

        if ratio >= min_overlap_ratio:
            return (col, row), score

        if score > best_finite_score:
            best_finite_score = score
            best_finite_loc = (col, row)

    if best_finite_loc is not None:
        logger.warning(
            "Ningún candidato superó overlap_ratio=%.2f. "
            "Usando mejor score finito: %.4f @ %s",
            min_overlap_ratio, best_finite_score, best_finite_loc,
        )
        return best_finite_loc, best_finite_score

    logger.warning("Mapa de correlación sin valores válidos. Devolviendo (0,0).")
    return (0, 0), 0.0


def _top_candidates_from_result(
    result_map: np.ndarray,
    image_mask: np.ndarray,
    tmpl_h: int,
    tmpl_w: int,
    n: int,
    min_overlap_ratio: float = 0.05,
) -> list[tuple[tuple, float]]:
    """
    Devuelve los top-N candidatos válidos del mapa de correlación,
    ordenados de mayor a menor score de forma.

    Se garantiza separación mínima entre candidatos (al menos max(tmpl_w, tmpl_h)//2
    píxeles) para no devolver variantes del mismo pico.

    Args:
        result_map: Mapa de correlación (H', W') float32.
        image_mask: Máscara binaria de la imagen (H, W) uint8.
        tmpl_h, tmpl_w: Dimensiones del template.
        n: Número máximo de candidatos a devolver.
        min_overlap_ratio: Fracción mínima del template con píxeles de forma.

    Returns:
        Lista de ((col, row), score_forma) ordenada de mayor a menor score.
    """
    tmpl_area = tmpl_h * tmpl_w
    safe_map = result_map.copy()
    safe_map[~np.isfinite(safe_map)] = -1.0

    flat = safe_map.flatten()
    pool_size = min(n * 20, flat.size)
    top_indices = np.argpartition(flat, -pool_size)[-pool_size:]
    top_indices = top_indices[np.argsort(flat[top_indices])[::-1]]

    img_h, img_w = image_mask.shape
    min_dist = max(tmpl_w, tmpl_h) // 2
    accepted: list[tuple[tuple, float]] = []

    for idx in top_indices:
        if len(accepted) >= n:
            break
        score = float(flat[idx])
        if score < 0:
            break

        row = int(idx // safe_map.shape[1])
        col = int(idx % safe_map.shape[1])

        # Filtro overlap
        r0, r1 = row, min(row + tmpl_h, img_h)
        c0, c1 = col, min(col + tmpl_w, img_w)
        ratio = int(np.count_nonzero(image_mask[r0:r1, c0:c1])) / tmpl_area
        if ratio < min_overlap_ratio:
            continue

        # Filtro distancia (evitar duplicados del mismo pico)
        too_close = any(
            abs(col - ac) < min_dist and abs(row - ar) < min_dist
            for (ac, ar), _ in accepted
        )
        if too_close:
            continue

        accepted.append(((col, row), score))

    return accepted


def color_chaos_score(
    png_arr: np.ndarray,
    image_mask: np.ndarray,
    top_left: tuple,
    tmpl_h: int,
    tmpl_w: int,
) -> float:
    """
    Mide el "caos cromático" en la región del match propuesta.

    El eco fijo es ruido electromagnético de terreno: devuelve señales
    incoherentes pintadas con colores aleatorios y fragmentados, sin patrón
    cromático dominante. La precipitación real tiene colores coherentes y
    graduales (verde → amarillo → rojo).

    Métricas combinadas (todas normalizadas a [0, 1]):

    1. Diversidad de colores cuantizados:
       Reduce la paleta a 8 niveles por canal y cuenta combinaciones únicas.
       Más colores distintos → más caos.

    2. Varianza espacial local (gradiente promedio):
       Gradiente Sobel en la región. Alta varianza → píxeles vecinos muy
       diferentes → caos.

    3. Ausencia de color dominante (entropía del tono Hue en HSV):
       Distribución plana de tonos → alta entropía → caos. Precipitación
       real concentra verde o amarillo.

    Solo se evalúan los píxeles que son forma (image_mask == 255) dentro
    de la ventana del candidato.

    Args:
        png_arr: Array original con color (H, W, C) uint8.
        image_mask: Máscara binaria de la imagen (H, W) uint8.
        top_left: (col, row) esquina superior izquierda del candidato.
        tmpl_h, tmpl_w: Dimensiones del template.

    Returns:
        float en [0, 1]: 0 = zona uniforme/monocromática, 1 = máximo caos.
    """
    col, row = int(top_left[0]), int(top_left[1])
    img_h, img_w = png_arr.shape[:2]

    r0 = max(row, 0)
    r1 = min(row + tmpl_h, img_h)
    c0 = max(col, 0)
    c1 = min(col + tmpl_w, img_w)

    if r1 <= r0 or c1 <= c0:
        return 0.0

    region_color = png_arr[r0:r1, c0:c1]
    region_mask  = image_mask[r0:r1, c0:c1]

    form_pixels = np.count_nonzero(region_mask)
    if form_pixels < 20:
        return 0.0

    mask_bool = region_mask == 255
    rgb = region_color[:, :, :3][mask_bool] if region_color.ndim == 3 else np.stack(
        [region_color[mask_bool]] * 3, axis=1
    )

    # ── Métrica 1: diversidad de colores cuantizados ──────────────────────
    quant = (rgb // 32).astype(np.int32)
    color_ids = quant[:, 0] * 64 + quant[:, 1] * 8 + quant[:, 2]
    diversity_score = min(len(np.unique(color_ids)) / MIN_UNIQUE_COLORS, 1.0)

    # ── Métrica 2: varianza espacial local (gradiente Sobel) ──────────────
    gray_region = cv2.cvtColor(
        region_color[:, :, :3].astype(np.uint8), cv2.COLOR_RGB2GRAY
    ).astype(np.float32)
    gray_masked = gray_region.copy()
    gray_masked[~mask_bool] = 0.0

    grad_x = cv2.Sobel(gray_masked, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray_masked, cv2.CV_32F, 0, 1, ksize=3)
    mean_grad = float(np.sqrt(grad_x**2 + grad_y**2)[mask_bool].mean())
    gradient_score = min(mean_grad / 50.0, 1.0)

    # ── Métrica 3: entropía del tono (Hue) ───────────────────────────────
    hsv_img = cv2.cvtColor(region_color[:, :, :3].astype(np.uint8), cv2.COLOR_RGB2HSV)
    hue_vals = hsv_img[:, :, 0][mask_bool]
    sat_vals  = hsv_img[:, :, 1][mask_bool]
    colored   = hue_vals[sat_vals > 30]

    if len(colored) > 10:
        hist, _ = np.histogram(colored, bins=18, range=(0, 180))
        p = hist.astype(np.float32)
        p = p[p > 0] / p.sum()
        entropy_score = min(float(-np.sum(p * np.log2(p))) / np.log2(18), 1.0)
    else:
        entropy_score = 0.0

    chaos = (diversity_score + gradient_score + entropy_score) / 3.0
    logger.debug(
        "      caos @ (%d,%d): div=%.3f grad=%.3f entr=%.3f → %.3f",
        col, row, diversity_score, gradient_score, entropy_score, chaos,
    )
    return chaos


def match_template_binary(
    image_mask: np.ndarray,
    template_mask: np.ndarray,
    png_arr: np.ndarray | None = None,
) -> tuple[tuple[int, int], float, str]:
    """
    Template matching sobre máscaras binarias con estrategia dinámica en cascada,
    seguido de validación por caos cromático cuando png_arr está disponible.

    Problema que resuelve:
        TM_CCOEFF_NORMED compara pixel a pixel TODO el template contra la ventana
        de la imagen, incluyendo el fondo negro. Si hay precipitación/nubes cerca
        del eco fijo, el fondo del template no coincide con las nubes, bajando
        el score aunque la FORMA coincida.

        Adicionalmente, zonas de precipitación densa pueden tener forma binaria
        similar al eco fijo y "ganar" el matching. La validación por caos cromático
        descarta esas zonas: precipitación real = colores coherentes; eco fijo =
        colores caóticos y fragmentados.

    Estrategia:
        1. MASKED (TM_CCORR_NORMED + máscara de forma): ignora el fondo negro.
        2. CLASSIC (TM_CCOEFF_NORMED sin máscara): más robusto numéricamente.
        3. POOL UNIFICADO: se fusionan los top-COLOR_CANDIDATES de ambos métodos,
           se evalúa el caos cromático de cada posición única y se elige el
           candidato con mayor score combinado:
               score_combinado = (1 - COLOR_CHAOS_WEIGHT) * score_forma
                               + COLOR_CHAOS_WEIGHT * score_caos
           Si png_arr no está disponible, se usa solo el mejor score de forma
           (comportamiento original).

    Args:
        image_mask: Máscara de la imagen de radar (H, W) uint8.
        template_mask: Máscara del eco fijo (h, w) uint8 con h<H y w<W.
        png_arr: Array original con color (H, W, C) uint8, opcional.
                 Si se provee, activa la validación por caos cromático.

    Returns:
        Tupla ((col, fila), score_forma, method_used).
    """
    image_f   = image_mask.astype(np.float32)
    template_f = template_mask.astype(np.float32)
    tmpl_h, tmpl_w = template_mask.shape[:2]

    raw_results: dict[str, list[tuple[tuple, float]]] = {}

    # ── Método 1: Masked (TM_CCORR_NORMED + máscara) ─────────────────────────
    if np.count_nonzero(template_mask) > 0:
        try:
            result_masked = cv2.matchTemplate(
                image_f, template_f, cv2.TM_CCORR_NORMED,
                mask=template_mask.astype(np.float32),
            )
            candidates_m = _top_candidates_from_result(
                result_masked, image_mask, tmpl_h, tmpl_w, COLOR_CANDIDATES
            )
            if candidates_m:
                raw_results["masked"] = candidates_m
                logger.debug("    [masked] top: score=%.4f @ %s", candidates_m[0][1], candidates_m[0][0])
        except cv2.error as exc:
            logger.warning("    Masked matching no disponible: %s", exc)

    # ── Método 2: Classic (TM_CCOEFF_NORMED sin máscara) ─────────────────────
    try:
        result_classic = cv2.matchTemplate(image_f, template_f, cv2.TM_CCOEFF_NORMED)
        candidates_c = _top_candidates_from_result(
            result_classic, image_mask, tmpl_h, tmpl_w, COLOR_CANDIDATES
        )
        if candidates_c:
            raw_results["classic"] = candidates_c
            logger.debug("    [classic] top: score=%.4f @ %s", candidates_c[0][1], candidates_c[0][0])
    except cv2.error as exc:
        logger.warning("    Classic matching falló: %s", exc)

    if not raw_results:
        raise RuntimeError("Todos los métodos de template matching fallaron.")

    # ── Pool unificado: fusionar candidatos de ambos métodos ──────────────────
    # Para posiciones solapadas se conserva el mayor score de forma.
    min_dist = max(tmpl_w, tmpl_h) // 2
    unified: dict[tuple, tuple[float, str]] = {}  # loc → (score_forma, method)

    for method_name, candidates in raw_results.items():
        for loc, score_forma in candidates:
            if not _valid_score(score_forma):
                continue
            merged = False
            for existing_loc in list(unified.keys()):
                if abs(loc[0] - existing_loc[0]) < min_dist and abs(loc[1] - existing_loc[1]) < min_dist:
                    if score_forma > unified[existing_loc][0]:
                        unified[existing_loc] = (score_forma, method_name)
                    merged = True
                    break
            if not merged:
                unified[loc] = (score_forma, method_name)

    logger.debug("    Pool unificado: %d candidatos únicos", len(unified))

    # ── Selección por score combinado (forma + caos cromático) ────────────────
    best_loc: tuple | None = None
    best_score_forma = -1.0
    best_combined    = -1.0
    best_method      = ""

    for loc, (score_forma, method_name) in unified.items():
        if png_arr is not None:
            chaos    = color_chaos_score(png_arr, image_mask, loc, tmpl_h, tmpl_w)
            combined = (1.0 - COLOR_CHAOS_WEIGHT) * score_forma + COLOR_CHAOS_WEIGHT * chaos
        else:
            chaos    = float("nan")
            combined = score_forma

        chaos_str = f"{chaos:.3f}" if not np.isnan(chaos) else "n/a"
        logger.debug(
            "      [%s] loc=%s forma=%.4f caos=%s combinado=%.4f",
            method_name, loc, score_forma, chaos_str, combined,
        )

        if combined > best_combined:
            best_combined    = combined
            best_score_forma = score_forma
            best_loc         = loc
            best_method      = method_name

    # Fallback extremo (no debería ocurrir)
    if best_loc is None:
        for method_name, candidates in raw_results.items():
            if candidates:
                loc, score_forma = candidates[0]
                if _valid_score(score_forma) and score_forma > best_score_forma:
                    best_score_forma = score_forma
                    best_loc         = loc
                    best_method      = method_name

    if best_loc is None:
        logger.warning("No se encontró ningún candidato válido. Devolviendo (0,0).")
        best_loc         = (0, 0)
        best_score_forma = 0.0
        best_method      = "fallback"

    logger.info(
        "Match → [%s] score_forma=%.4f score_combinado=%.4f @ %s",
        best_method, best_score_forma, best_combined, best_loc,
    )
    return best_loc, best_score_forma, best_method


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
    5. Template matching en cascada (masked → classic) con validación por caos
       cromático: el eco fijo tiene colores caóticos (ruido de terreno), mientras
       que la precipitación real tiene colores coherentes. Se fusionan los
       candidatos de ambos métodos y se elige el de mayor score combinado
       (forma + caos).
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
        RuntimeError: Si todos los métodos de template matching fallan.
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

    eco_h, eco_w = eco_mask.shape
    if eco_h > height or eco_w > width:
        raise ValueError(
            f"Template eco ({eco_mask.shape}) mayor que la imagen ({png_mask.shape})."
        )

    # ── 5. Template matching con validación por caos cromático ───────────────
    top_left, score, method_used = match_template_binary(png_mask, eco_mask, filled_rgb)
    match_col, match_row = top_left
    logger.info(
        "Match: top_left=(%d, %d), score=%.4f, método=%s",
        match_col, match_row, score, method_used,
    )

    if score < MIN_MATCH_SCORE:
        logger.warning(
            "Score bajo (%.4f < %.4f). Match puede ser incorrecto.",
            score, MIN_MATCH_SCORE,
        )

    # ── 6. Calcular delta geográfico ──────────────────────────────────────────
    eco_center_col = match_col + (eco_w - 1) / 2.0
    eco_center_row = match_row + (eco_h - 1) / 2.0

    eco_found_lon, eco_found_lat = pixel_to_geo(ref_transform, eco_center_col, eco_center_row)
    eco_true_lon, eco_true_lat = get_center_geo(eco_transform, eco_width, eco_height)

    delta_lon = eco_true_lon - eco_found_lon
    delta_lat = eco_true_lat - eco_found_lat
    logger.info("Δlon=%.4f, Δlat=%.4f", delta_lon, delta_lat)

    # ── 7. Corregir Transform ─────────────────────────────────────────────────
    corrected_transform = correct_transform(ref_transform, delta_lon, delta_lat)

    # ── 8. Construir máscara booleana de clutter ──────────────────────────────
    # Solo se enmascaran los píxeles que son forma del eco (eco_mask > 0),
    # no todo el bounding box, para no eliminar precipitación real adyacente.
    clutter_mask = np.zeros((height, width), dtype=bool)
    row_end = min(match_row + eco_h, height)
    col_end = min(match_col + eco_w, width)
    clutter_mask[match_row:row_end, match_col:col_end] = (
        eco_mask[:row_end - match_row, :col_end - match_col] > 0
    )
    logger.info(
        "clutter_mask: %d píxeles de eco fijo enmascarados",
        int(np.count_nonzero(clutter_mask)),
    )

    # ── 9. Generar GeoTIFF final en memoria, sin ecos fijos ───────────────────
    # Se trabaja sobre una copia para no modificar filled_rgb (el orquestador
    # puede necesitarlo para métricas u otras fases del pipeline).
    export_rgb = filled_rgb.copy()
    export_rgb[clutter_mask] = 0
    logger.info("GeoTIFF exportado con ecos fijos enmascarados (NoData=0)")

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