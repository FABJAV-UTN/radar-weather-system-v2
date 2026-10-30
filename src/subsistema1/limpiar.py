from __future__ import annotations

# src/subsistema1/limpiar.py
"""
Fase 4 del pipeline: Limpieza de píxeles y clasificación dBZ.

Siempre se ejecuta, independientemente de si hubo crop.
- Elimina colores del marco/borde (#5f9ea0).
- Clasifica cada píxel en uno de los 16 niveles dBZ con una TABLA DE
  REFERENCIA única: los 16 colores puros de la escala + los colores que
  deja la marca de agua del DACC sobre cada nivel (modelo de mezcla).
- Pinta cada píxel con el color puro de su nivel.
- Genera la máscara de huecos de la región fija de la esquina.

Modelo de mezcla de la marca de agua
------------------------------------
La marca (logotipo "DACC" y texto "Dirección de Agricultura y Contingencias
Climáticas") se superpone semitransparente sobre el dato:

    observado = W + alfa · D        (recortado a 0-255)

D es el color puro de la escala, W el color que la marca deja sobre fondo
negro y alfa la fracción del dato que queda visible (≈ 0,85 en el interior
de la marca; más cerca de 1 en los bordes suavizados). W y alfa se miden con
scripts/medir_marca_agua.py (GIF seco + GIF con lluvia del 13/10/2026).

Cada color se compara UNA sola vez contra toda la tabla y gana la entrada
más cercana. Así un color puro de la escala (distancia 0 a sí mismo) nunca
puede reasignarse a otro nivel, y un color alterado por la marca vuelve a su
nivel real. La corrección no depende de la posición de la marca ni del
tamaño de la imagen.

Sin I/O: opera sobre PIL.Image en memoria, devuelve arrays numpy.
"""

import numpy as np
from PIL import Image

# ── Constantes ────────────────────────────────────────────────────────────────

# Región fija de la esquina superior izquierda que se marca como hueco para la
# Fase 5. No es la marca de agua del DACC (que está en el centro del mapa y se
# corrige por color, ver MARCA_AGUA_COMPONENTES).
WATERMARK_REGION: dict[str, int] = {"x": 0, "y": 0, "w": 120, "h": 30}
DEFAULT_COLOR_THRESHOLD: float = 30.0

# Colores del marco/borde a eliminar (pueden aparecer como residuos del crop)
FRAME_COLORS: list[tuple[tuple[int, int, int], float]] = [
    ((95, 158, 160), 20.0),   # #5f9ea0 — cadet blue (marco DACC)
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

# Componentes de la marca de agua: (W, alfa). Medidos el 30/10/2026 con
# scripts/medir_marca_agua.py: W = color más frecuente de cada píxel en 51 GIF
# secos (seco.gif del 19/10 y 50 del 27/10/2026, 17:38-20:22) y alfa ajustado
# en 64 GIF originales del 13/10/2026 (variante 707 × 842). Los tres primeros
# son el interior de la marca (logotipo oliva, logotipo azul, letras grises);
# el resto son sus bordes suavizados y variantes de paleta (alfa más cerca de 1).
MARCA_AGUA_COMPONENTES: tuple[tuple[tuple[int, int, int], float], ...] = (
    ((24, 30, 8), 0.86),   # 12195 px — logotipo, parte inferior (oliva)
    ((11, 19, 27), 0.86),  # 10325 px — logotipo, parte superior (azul)
    ((37, 37, 37), 0.84),  #  7268 px — letras "DACC" y texto
    ((28, 28, 28), 0.88),  #  1500 px
    ((20, 20, 20), 0.92),  #  1134 px
    ((11, 11, 11), 0.94),  #   839 px
    ((5, 7, 8), 0.97),     #   789 px
    ((7, 8, 6), 0.97),     #   776 px
    ((7, 9, 11), 0.95),    #   553 px
    ((22, 27, 11), 0.89),  #   346 px
    ((10, 14, 18), 0.91),  #   219 px
    ((24, 29, 7), 0.87),   #   211 px
    ((9, 10, 7), 0.95),    #   148 px
    ((11, 17, 22), 0.87),  #   131 px
    ((23, 29, 7), 0.85),   #    82 px
    ((25, 29, 17), 0.86),  #    81 px
    ((27, 32, 18), 0.85),  #    24 px
)


# Arrays precomputados
DBZ_VALUES: np.ndarray = np.array(list(DBZ_COLOR_MAP.keys()), dtype=np.int32)
DBZ_COLORS: np.ndarray = np.array(list(DBZ_COLOR_MAP.values()), dtype=np.float32)
FRAME_COLOR_ARRAY: np.ndarray = np.array(
    [c[0] for c in FRAME_COLORS], dtype=np.float32
)
FRAME_TOLERANCE_ARRAY: np.ndarray = np.array(
    [c[1] for c in FRAME_COLORS], dtype=np.float32
)


def construir_tabla_referencia(
    componentes: tuple[tuple[tuple[int, int, int], float], ...] = MARCA_AGUA_COMPONENTES,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Arma la tabla de referencia de la clasificación.

    Contiene los 16 colores puros de la escala y, para cada componente
    (W, alfa) de la marca, los 16 colores alterados W + alfa · D (recortados
    a 0-255), cada uno con el dBZ de su color puro D.

    Returns:
        (colores, dbz): arrays (N, 3) float32 y (N,) int32, con
        N = 16 · (1 + len(componentes)). Las 16 primeras filas son los puros.
    """
    colores = [DBZ_COLORS]
    valores = [DBZ_VALUES]
    for w, alfa in componentes:
        alterados = np.clip(np.asarray(w, dtype=np.float32) + alfa * DBZ_COLORS, 0, 255)
        colores.append(alterados.astype(np.float32))
        valores.append(DBZ_VALUES)
    return np.concatenate(colores), np.concatenate(valores)


TABLA_COLORES, TABLA_DBZ = construir_tabla_referencia()


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
    Clasifica cada píxel en un nivel dBZ con la tabla de referencia.

    Cada color distinto de la imagen se compara una sola vez contra toda la
    tabla (16 puros + colores alterados por la marca) y toma el dBZ de la
    entrada más cercana. Si esa distancia supera `threshold`, el píxel queda
    en 0 (no es dato de tormenta).

    Se trabaja sobre los colores únicos (un GIF tiene a lo sumo 256), no
    píxel por píxel.

    Args:
        rgb_array: Array numpy (H, W, 3) uint8.
        threshold: Distancia euclídea RGB máxima a la entrada más cercana.

    Returns:
        Array (H, W) int32 con valores dBZ (0 = no tormenta).
    """
    h, w = rgb_array.shape[:2]
    flat = rgb_array.reshape(-1, 3)
    colores, inversa = np.unique(flat, axis=0, return_inverse=True)
    inversa = inversa.reshape(-1)

    diff = colores.astype(np.float32)[:, np.newaxis, :] - TABLA_COLORES[np.newaxis, :, :]
    distancias = np.linalg.norm(diff, axis=2)           # (colores, entradas)
    idx = np.argmin(distancias, axis=1)
    dist_min = distancias[np.arange(len(colores)), idx]

    dbz_por_color = np.where(dist_min <= threshold, TABLA_DBZ[idx], 0).astype(np.int32)
    return dbz_por_color[inversa].reshape(h, w)


def dbz_a_rgb(dbz_map: np.ndarray) -> np.ndarray:
    """Pinta cada píxel con el color puro de su nivel dBZ (0 → negro)."""
    rgb = np.zeros((*dbz_map.shape, 3), dtype=np.uint8)
    for dbz, color in DBZ_COLOR_MAP.items():
        rgb[dbz_map == dbz] = color
    return rgb


def clean_image(
    image: Image.Image,
    color_threshold: float = DEFAULT_COLOR_THRESHOLD,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Limpia una imagen de radar: elimina el marco, corrige la marca de agua y
    clasifica los píxeles en niveles dBZ.

    Pasos:
    1. Eliminar colores del marco/borde (cadet blue).
    2. Clasificar con la tabla de referencia (puros + modelo de mezcla).
    3. Generar la máscara de huecos de la región fija de la esquina.
    4. Construir la imagen limpia con el color puro de cada nivel.

    Args:
        image: Imagen PIL (cualquier modo; se convierte a RGB internamente).
        color_threshold: Distancia máxima a la tabla para clasificar un píxel.

    Returns:
        Tupla (clean_rgb, gap_mask, dbz_map):
        - clean_rgb: Array (H, W, 3) uint8. Color puro de cada nivel; resto negro.
        - gap_mask: Array booleano (H, W). True en huecos de la región fija.
        - dbz_map: Array (H, W) int32. Valor dBZ de cada píxel (0 = no tormenta).
    """
    if getattr(image, "is_animated", False):
        image.seek(0)

    rgb = np.array(image.convert("RGB"))
    h, w = rgb.shape[:2]

    # ── Paso 1: eliminar píxeles de marco ────────────────────────────────────
    # Se evalúa sobre los colores únicos para no comparar píxel por píxel.
    colores, inversa = np.unique(rgb.reshape(-1, 3), axis=0, return_inverse=True)
    es_marco = _is_competitive_frame_pixel(colores.astype(np.float32))
    frame_mask = es_marco[inversa.reshape(-1)].reshape(h, w)
    rgb_no_frame = rgb.copy()
    rgb_no_frame[frame_mask] = 0

    # ── Paso 2: clasificar (puros + colores alterados por la marca) ─────────
    dbz_map = classify_array(rgb_no_frame, color_threshold)

    # ── Paso 3: máscara de huecos de la región fija ─────────────────────────
    storm_mask = dbz_map > 0
    wm = WATERMARK_REGION
    y_start, x_start = wm["y"], wm["x"]
    y_end = min(y_start + wm["h"], h)
    x_end = min(x_start + wm["w"], w)
    region_mask = np.zeros((h, w), dtype=bool)
    region_mask[y_start:y_end, x_start:x_end] = True
    gap_mask = region_mask & ~storm_mask

    # ── Paso 4: imagen limpia con colores puros ──────────────────────────────
    clean_rgb = dbz_a_rgb(dbz_map)

    return clean_rgb, gap_mask, dbz_map
