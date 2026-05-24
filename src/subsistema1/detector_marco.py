# src/subsistema1/detector_marco.py
"""
Fase 2 del pipeline: Detección de marco DACC en imágenes de radar.

Detecta si la imagen contiene el marco/banner característico del radar DACC
Mendoza buscando el color #5e9d9f desde los 4 bordes hacia el centro.
Si al menos 3 de 4 bordes detectan el color, la imagen tiene marco.

Sin I/O: opera sobre PIL.Image en memoria.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

# ── Constantes ────────────────────────────────────────────────────────────────
FRAME_COLOR_RGB: tuple[int, int, int] = (94, 157, 159)  # #5e9d9f — cadet blue
FRAME_TOLERANCE: int = 15
MIN_BORDES_DETECTADOS: int = 3
MIN_ANCHO: int = 200
MIN_ALTO: int = 150


# ── Helpers (funciones puras, sin efectos laterales) ─────────────────────────

def _pixel_matches(
    pixel: np.ndarray,
    target_rgb: tuple[int, int, int],
    tolerance: int,
) -> bool:
    """
    Comprueba si un píxel RGB coincide con el color objetivo dentro de tolerancia.

    Args:
        pixel: Array de 3 elementos [R, G, B].
        target_rgb: Color objetivo como tupla (R, G, B).
        tolerance: Margen máximo por canal.

    Returns:
        True si el píxel está dentro de la tolerancia en los 3 canales.
    """
    return (
        abs(int(pixel[0]) - target_rgb[0]) <= tolerance
        and abs(int(pixel[1]) - target_rgb[1]) <= tolerance
        and abs(int(pixel[2]) - target_rgb[2]) <= tolerance
    )


def _find_color_in_scanline(
    arr: np.ndarray,
    row_or_col: int,
    color_ref: tuple[int, int, int],
    tolerancia: int,
    is_row: bool = True,
    from_end: bool = True,
    num_apariciones: int = 1,
) -> tuple[int | None, int]:
    """
    Busca el color de referencia en una línea de escaneo (fila o columna).

    Args:
        arr: Array numpy (H, W, 3).
        row_or_col: Índice de la fila o columna a escanear.
        color_ref: Color buscado como tupla RGB.
        tolerancia: Margen de tolerancia por canal.
        is_row: True para escanear fila, False para columna.
        from_end: True para empezar desde el final, False desde el inicio.
        num_apariciones: Número de apariciones a contar antes de devolver.

    Returns:
        Tupla (posición_encontrada | None, contador_total).
    """
    if is_row:
        length = arr.shape[1]
        rango = range(length - 1, -1, -1) if from_end else range(length)
        get_pixel = lambda idx: arr[row_or_col, idx]  # noqa: E731
    else:
        length = arr.shape[0]
        rango = range(length - 1, -1, -1) if from_end else range(length)
        get_pixel = lambda idx: arr[idx, row_or_col]  # noqa: E731

    contador = 0
    for idx in rango:
        if _pixel_matches(get_pixel(idx), color_ref, tolerancia):
            contador += 1
            if contador == num_apariciones:
                return idx, contador
    return None, contador


# ── API pública ───────────────────────────────────────────────────────────────

def detectar_marco(
    image: Image.Image,
    tolerancia: int = FRAME_TOLERANCE,
) -> bool:
    """
    Detecta si una imagen PIL tiene el marco/banner del DACC Mendoza.

    Estrategia: busca el color #5e9d9f desde los 4 bordes hacia el centro.
    Si al menos 3 de 4 bordes detectan el patrón, la imagen tiene marco.

    Args:
        image: Imagen PIL (cualquier modo; se convierte a RGB internamente).
        tolerancia: Margen de tolerancia para la comparación de color.

    Returns:
        True si la imagen tiene marco DACC, False en caso contrario.
    """
    # Convertir a RGB; manejar GIF animado tomando el frame 0
    if getattr(image, "is_animated", False):
        image.seek(0)
    if image.mode != "RGB":
        image = image.convert("RGB")

    arr = np.array(image)
    alto, ancho = arr.shape[0], arr.shape[1]

    # Imagen demasiado pequeña para tener marco
    if ancho < MIN_ANCHO or alto < MIN_ALTO:
        return False

    fila_central = alto // 2
    col_central = ancho // 2
    color_ref = FRAME_COLOR_RGB
    bordes_detectados = 0

    # 1. Desde derecha (fila central, 4ª aparición)
    col, _ = _find_color_in_scanline(
        arr, fila_central, color_ref, tolerancia,
        is_row=True, from_end=True, num_apariciones=4,
    )
    if col is not None:
        bordes_detectados += 1

    # 2. Desde izquierda (fila central, 1ª aparición)
    col, _ = _find_color_in_scanline(
        arr, fila_central, color_ref, tolerancia,
        is_row=True, from_end=False, num_apariciones=1,
    )
    if col is not None:
        bordes_detectados += 1

    # 3. Desde arriba (columna central, 4ª aparición)
    row, _ = _find_color_in_scanline(
        arr, col_central, color_ref, tolerancia,
        is_row=False, from_end=False, num_apariciones=4,
    )
    if row is not None:
        bordes_detectados += 1

    # 4. Desde abajo (columna central, 2ª aparición)
    row, _ = _find_color_in_scanline(
        arr, col_central, color_ref, tolerancia,
        is_row=False, from_end=True, num_apariciones=2,
    )
    if row is not None:
        bordes_detectados += 1

    return bordes_detectados >= MIN_BORDES_DETECTADOS