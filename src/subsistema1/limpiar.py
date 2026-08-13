from __future__ import annotations

# src/subsistema1/limpiar.py
"""
Fase 4 del pipeline: Limpieza de píxeles y clasificación dBZ.

Siempre se ejecuta, independientemente de si hubo crop.
- Elimina colores del marco/borde (#5f9ea0, #fffd01).
- Clasifica cada píxel al valor dBZ más cercano por distancia euclídea RGB.
- Detecta la región de watermark (esquina sup-izq) y genera máscara de huecos.

Sin I/O: opera sobre PIL.Image en memoria, devuelve arrays numpy.
"""

import numpy as np
from PIL import Image

# ── Constantes ────────────────────────────────────────────────────────────────
WATERMARK_REGION: dict[str, int] = {"x": 0, "y": 0, "w": 120, "h": 30}
DEFAULT_COLOR_THRESHOLD: float = 30.0

# Colores del marco/borde a eliminar (pueden aparecer como residuos del crop)
FRAME_COLORS: list[tuple[tuple[int, int, int], float]] = [
    ((95, 158, 160), 20.0),   # #5f9ea0 — cadet blue (marco)
    ((255, 253, 1), 25.0),    # #fffd01 — amarillo brillante (marco)
]

# Mapa dBZ → color RGB. 16 niveles de 10 a 80 dBZ.
DBZ_COLOR_MAP: dict[int, tuple[int, int, int]] = {
    10: (72, 61, 139),
    20: (0, 90, 0),
    30: (0, 112, 0),
    35: (8, 127, 219),
    36: (28, 71, 232),
    39: (110, 13, 198),
    42: (200, 15, 134),
    45: (192, 100, 135),
    48: (210, 136, 59),
    51: (250, 196, 49),
    54: (252, 252, 12),
    57: (254, 154, 88),
    60: (254, 95, 5),
    65: (253, 52, 28),
    70: (190, 190, 190),
    80: (211, 211, 211),
}

# Arrays precomputados para vectorizar la clasificación
DBZ_VALUES: np.ndarray = np.array(list(DBZ_COLOR_MAP.keys()), dtype=np.int32)
DBZ_COLORS: np.ndarray = np.array(list(DBZ_COLOR_MAP.values()), dtype=np.float32)
FRAME_COLOR_ARRAY: np.ndarray = np.array(
    [c[0] for c in FRAME_COLORS], dtype=np.float32
)
FRAME_TOLERANCE_ARRAY: np.ndarray = np.array(
    [c[1] for c in FRAME_COLORS], dtype=np.float32
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_frame_pixel(rgb_flat: np.ndarray) -> np.ndarray:
    """
    Detecta píxeles que pertenecen al marco/borde de la imagen.

    Args:
        rgb_flat: Array de shape (N, 3) con píxeles RGB aplanados.

    Returns:
        Máscara booleana de shape (N,) con True para píxeles de marco.
    """
    diff = rgb_flat[:, np.newaxis, :] - FRAME_COLOR_ARRAY[np.newaxis, :, :]
    distances = np.linalg.norm(diff, axis=2)  # (N, num_frame_colors)
    within_tolerance = distances <= FRAME_TOLERANCE_ARRAY[np.newaxis, :]
    return np.any(within_tolerance, axis=1)


def _is_competitive_frame_pixel(rgb_flat: np.ndarray) -> np.ndarray:
    """Marca píxeles de marco solo si son más cercanos al marco que a cualquier dBZ."""
    frame_diff = rgb_flat[:, np.newaxis, :] - FRAME_COLOR_ARRAY[np.newaxis, :, :]
    frame_distances = np.linalg.norm(frame_diff, axis=2)
    within_frame_tolerance = frame_distances <= FRAME_TOLERANCE_ARRAY[np.newaxis, :]

    dbz_diff = rgb_flat[:, np.newaxis, :] - DBZ_COLORS[np.newaxis, :, :]
    dbz_distances = np.linalg.norm(dbz_diff, axis=2)

    frame_min_distance = np.min(frame_distances, axis=1)
    dbz_min_distance = np.min(dbz_distances, axis=1)
    return np.any(within_frame_tolerance, axis=1) & (frame_min_distance < dbz_min_distance)


# ── API pública ───────────────────────────────────────────────────────────────

def classify_array(
    rgb_array: np.ndarray,
    threshold: float = DEFAULT_COLOR_THRESHOLD,
) -> np.ndarray:
    """
    Clasifica cada píxel al valor dBZ más cercano por distancia euclídea RGB.

    Si la distancia mínima al color dBZ más cercano supera `threshold`,
    el píxel queda como 0 (no es dato de tormenta).

    Args:
        rgb_array: Array numpy (H, W, 3) uint8.
        threshold: Distancia máxima euclídea para considerar un píxel como dBZ válido.

    Returns:
        Array (H, W) int32 con valores dBZ (0 = no tormenta).
    """
    h, w = rgb_array.shape[:2]
    flat = rgb_array.reshape(-1, 3).astype(np.float32)
    diff = flat[:, np.newaxis, :] - DBZ_COLORS[np.newaxis, :, :]
    distances = np.linalg.norm(diff, axis=2)
    min_idx = np.argmin(distances, axis=1)
    min_dist = distances[np.arange(len(flat)), min_idx]
    result = np.zeros(len(flat), dtype=np.int32)
    mask = min_dist <= threshold
    result[mask] = DBZ_VALUES[min_idx[mask]]
    return result.reshape(h, w)


def clean_image(
    image: Image.Image,
    color_threshold: float = DEFAULT_COLOR_THRESHOLD,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Limpia una imagen de radar eliminando el marco y clasificando píxeles dBZ.

    Pasos:
    1. Eliminar colores del marco/borde (cadet blue y amarillo).
    2. Clasificar píxeles por distancia euclídea al mapa dBZ.
    3. Detectar región de watermark y generar máscara de huecos.
    4. Construir imagen limpia con solo los píxeles de tormenta.

    Args:
        image: Imagen PIL (cualquier modo; se convierte a RGB internamente).
        color_threshold: Distancia máxima al color dBZ para clasificar un píxel.

    Returns:
        Tupla (clean_rgb, gap_mask, dbz_map):
        - clean_rgb: Array (H, W, 3) uint8. Solo píxeles de tormenta; resto en negro.
        - gap_mask: Array booleano (H, W). True en píxeles a rellenar (watermark).
        - dbz_map: Array (H, W) int32. Valor dBZ de cada píxel (0 = no tormenta).
    """
    if getattr(image, "is_animated", False):
        image.seek(0)

    rgb = np.array(image.convert("RGB"))
    h, w = rgb.shape[:2]

    # ── Paso 0: eliminar píxeles de marco ────────────────────────────────────
    flat = rgb.reshape(-1, 3).astype(np.float32)
    frame_mask = _is_competitive_frame_pixel(flat).reshape(h, w)
    rgb_no_frame = rgb.copy()
    rgb_no_frame[frame_mask] = 0

    # ── Paso 1: clasificar por dBZ ───────────────────────────────────────────
    dbz_map = classify_array(rgb_no_frame, color_threshold)
    storm_mask = dbz_map > 0

    # ── Paso 2: detectar watermark y generar máscara de huecos ──────────────
    wm = WATERMARK_REGION
    watermark_mask = np.zeros((h, w), dtype=bool)
    watermark_mask[wm["y"]:wm["y"] + wm["h"], wm["x"]:wm["x"] + wm["w"]] = True
    gap_mask = watermark_mask & ~storm_mask

    # ── Paso 3: imagen limpia ─────────────────────────────────────────────────
    clean_rgb = np.zeros_like(rgb)
    clean_rgb[storm_mask] = rgb_no_frame[storm_mask]

    return clean_rgb, gap_mask, dbz_map