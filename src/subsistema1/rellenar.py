from __future__ import annotations

# src/subsistema1/rellenar.py
"""
Fase 5 del pipeline: Relleno espacial de huecos (inpainting).

Siempre se ejecuta después de la limpieza.
- Relleno de líneas divisorias, textos y residuos sin reflectividad recuperable.
- Relleno de huecos internos: scipy binary_fill_holes + mediana del borde.

Sin I/O: opera sobre arrays numpy en memoria.
"""

import numpy as np
from scipy import ndimage


# ── Helpers ───────────────────────────────────────────────────────────────────

def _detect_thin_gaps(storm_mask: np.ndarray, min_storm_neighbors: int = 5) -> np.ndarray:
    """Detecta huecos delgados rodeados mayormente por tormenta, aunque no estén cerrados."""
    if storm_mask.ndim != 2:
        raise ValueError("storm_mask debe ser de 2 dimensiones")

    kernel = np.ones((3, 3), dtype=np.uint8)
    kernel[1, 1] = 0
    neighbor_count = ndimage.convolve(storm_mask.astype(np.uint8), kernel, mode="constant", cval=0)
    return (~storm_mask) & (neighbor_count >= min_storm_neighbors)


def _fill_watermark_region(
    rgb: np.ndarray,
    storm_mask: np.ndarray,
    gap_mask: np.ndarray,
    max_passes: int = 10,
) -> np.ndarray:
    """
    Rellena huecos espaciales por votación de mayoría de vecinos.

    Para cada píxel del hueco, examina los 4 vecinos cardinales.
    Si al menos 2 tienen datos válidos, asigna el color más frecuente.
    Itera hasta max_passes o hasta que no queden píxeles sin rellenar.

    Args:
        rgb: Array (H, W, 3) uint8. Imagen limpia.
        storm_mask: Máscara booleana de píxeles con datos.
        gap_mask: Máscara booleana de huecos o residuos a rellenar.
        max_passes: Límite de iteraciones para evitar bucles infinitos.

    Returns:
        Array (H, W, 3) uint8 con los huecos rellenados.
    """
    result = rgb.copy()
    current_storm = storm_mask.copy()
    gap_coords = list(zip(*np.where(gap_mask & ~current_storm)))

    for _ in range(max_passes):
        if not gap_coords:
            break
        filled_any = False
        remaining = []
        for row, col in gap_coords:
            neighbors = []
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                r, c = row + dr, col + dc
                if (
                    0 <= r < current_storm.shape[0]
                    and 0 <= c < current_storm.shape[1]
                    and current_storm[r, c]
                ):
                    neighbors.append(tuple(result[r, c]))
            if len(neighbors) >= 2:
                unique, counts = np.unique(neighbors, axis=0, return_counts=True)
                color = unique[np.argmax(counts)]
                result[row, col] = color
                current_storm[row, col] = True
                filled_any = True
            else:
                remaining.append((row, col))
        gap_coords = remaining
        if not filled_any:
            break

    return result


def _border_median_color(
    rgb: np.ndarray,
    storm_mask: np.ndarray,
    region: np.ndarray,
) -> np.ndarray:
    """
    Calcula el color mediana del borde de una región de hueco.

    Se usa para rellenar huecos internos con el color representativo
    de su entorno inmediato.

    Args:
        rgb: Array (H, W, 3) uint8.
        storm_mask: Máscara booleana de píxeles con datos.
        region: Máscara booleana de la región de hueco.

    Returns:
        Color mediana como array (3,) uint8.
    """
    dilated = ndimage.binary_dilation(region)
    border = dilated & storm_mask & ~region
    if not border.any():
        return np.median(rgb[storm_mask], axis=0).astype(np.uint8)
    return np.median(rgb[border], axis=0).astype(np.uint8)


def _fill_internal_holes(
    rgb: np.ndarray,
    storm_mask: np.ndarray,
    min_hole_size: int = 4,
) -> np.ndarray:
    """
    Rellena huecos internos de la región de tormenta con el color mediana del borde.

    Usa scipy.ndimage.binary_fill_holes para detectar huecos completamente
    rodeados de píxeles válidos, luego los rellena con la mediana del borde.

    Args:
        rgb: Array (H, W, 3) uint8.
        storm_mask: Máscara booleana de píxeles válidos de tormenta.
        min_hole_size: Mínimo de píxeles para considerar un hueco.

    Returns:
        Array (H, W, 3) uint8 con huecos internos rellenados.
    """
    result = rgb.copy()
    filled = ndimage.binary_fill_holes(storm_mask)
    internal_holes = filled & ~storm_mask

    if not internal_holes.any():
        return result

    labeled, num_regions = ndimage.label(internal_holes)
    for region_id in range(1, num_regions + 1):
        region = labeled == region_id
        if region.sum() < min_hole_size:
            continue
        fill_color = _border_median_color(result, storm_mask, region)
        result[region] = fill_color

    return result


# ── API pública ───────────────────────────────────────────────────────────────

def fill_gaps(
    clean_rgb: np.ndarray,
    gap_mask: np.ndarray,
    fill_general_holes: bool = True,
    min_hole_size: int = 4,
) -> np.ndarray:
    """
    Rellena todos los huecos de la imagen limpia de radar.

    Orden de operaciones:
    1. Inpainting espacial de líneas, textos y residuos indicados por las máscaras.
    2. Relleno de huecos internos dentro de la tormenta (opcional).

    Args:
        clean_rgb: Array (H, W, 3) uint8. Imagen post-limpieza.
        gap_mask: Máscara booleana (H, W). True en huecos o residuos a rellenar.
        fill_general_holes: Si True, también rellena huecos internos de la tormenta.
        min_hole_size: Tamaño mínimo (píxeles) para rellenar un hueco interno.

    Returns:
        Array (H, W, 3) uint8 con todos los huecos rellenados.
    """
    storm_mask = np.any(clean_rgb > 0, axis=2)
    result = clean_rgb.copy()

    # 1. Rellenar huecos espaciales y residuos
    line_gaps = _detect_thin_gaps(storm_mask, min_storm_neighbors=5)
    combined_gap_mask = gap_mask | line_gaps
    if combined_gap_mask.any():
        result = _fill_watermark_region(result, storm_mask, combined_gap_mask)
        storm_mask = np.any(result > 0, axis=2)

    # 2. Rellenar huecos internos
    if fill_general_holes:
        result = _fill_internal_holes(result, storm_mask, min_hole_size)

    return result