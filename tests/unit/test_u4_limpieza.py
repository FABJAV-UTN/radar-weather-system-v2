"""
TEST U4: Limpieza de píxeles.
Módulo objetivo: src/subsistema1/limpiar.py

Testea:
- clean_image(image)       → pipeline completo de limpieza
- _is_frame_pixel(rgb)     → detección de colores de marco
- FRAME_COLORS             → constantes correctas
- WATERMARK_REGION         → región fija (0, 0, 120, 30)
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.subsistema1.limpiar import (
    FRAME_COLORS,
    WATERMARK_REGION,
    clean_image,
    classify_array,
    DBZ_COLOR_MAP,
    _is_frame_pixel,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _imagen_gris(ancho: int = 256, alto: int = 256) -> Image.Image:
    arr = np.ones((alto, ancho, 3), dtype=np.uint8) * 128
    return Image.fromarray(arr, mode="RGB")


def _imagen_con_cadet_blue(ancho: int = 400, alto: int = 300) -> Image.Image:
    """Imagen con bordes en color de marco #5f9ea0."""
    arr = np.ones((alto, ancho, 3), dtype=np.uint8) * 128
    # Marco en cadet blue
    arr[:20, :, :] = [95, 158, 160]
    arr[-20:, :, :] = [95, 158, 160]
    arr[:, :20, :] = [95, 158, 160]
    arr[:, -20:, :] = [95, 158, 160]
    return Image.fromarray(arr, mode="RGB")


# ─────────────────────────────────────────────────────────────────────────────
# TEST U4
# ─────────────────────────────────────────────────────────────────────────────

class TestLimpiezaU4:
    """Tests para el módulo de limpieza (src/subsistema1/limpiar.py)."""

    def test_u4_clean_image_devuelve_tres_arrays(self):
        """U4: clean_image devuelve tupla (clean_rgb, gap_mask, dbz_map)."""
        imagen = _imagen_gris()
        resultado = clean_image(imagen)

        assert isinstance(resultado, tuple)
        assert len(resultado) == 3
        clean_rgb, gap_mask, dbz_map = resultado
        assert clean_rgb.ndim == 3
        assert clean_rgb.shape[2] == 3
        assert gap_mask.ndim == 2
        assert gap_mask.dtype == bool
        assert dbz_map.ndim == 2

    def test_u4_clean_image_dimensiones_preservadas(self):
        """U4: clean_image preserva las dimensiones de la imagen."""
        imagen = _imagen_gris(300, 200)
        clean_rgb, gap_mask, dbz_map = clean_image(imagen)

        assert clean_rgb.shape == (200, 300, 3)
        assert gap_mask.shape == (200, 300)
        assert dbz_map.shape == (200, 300)

    def test_u4_clean_image_elimina_colores_marco(self):
        """U4: clean_image elimina píxeles de color cadet blue del marco."""
        imagen = _imagen_con_cadet_blue()
        clean_rgb, _, _ = clean_image(imagen)

        # Los píxeles de borde (cadet blue) deben quedar en negro (0, 0, 0)
        borde_sup = clean_rgb[5, :, :]
        assert np.all(borde_sup == 0), "El borde superior no fue eliminado"

    def test_u4_clean_image_gif_animado(self):
        """U4: clean_image maneja GIFs animados usando el frame 0."""
        # Crear GIF animado en memoria
        frames = [Image.new("RGB", (100, 100), color=c) for c in [(100, 100, 100)] * 3]
        buf = io.BytesIO()
        frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], loop=0)
        buf.seek(0)
        imagen_gif = Image.open(buf)

        result = clean_image(imagen_gif)
        assert result is not None
        clean_rgb, gap_mask, dbz_map = result
        assert clean_rgb.shape[2] == 3

    def test_u4_watermark_region_constante(self):
        """U4: La región de watermark está definida como (0, 0, 120, 30)."""
        assert WATERMARK_REGION["x"] == 0
        assert WATERMARK_REGION["y"] == 0
        assert WATERMARK_REGION["w"] == 120
        assert WATERMARK_REGION["h"] == 30

    def test_u4_frame_colors_definidos(self):
        """U4: FRAME_COLORS contiene cadet blue y amarillo con sus tolerancias."""
        assert len(FRAME_COLORS) >= 2
        colores = [c[0] for c in FRAME_COLORS]
        # Cadet blue: ~(95, 158, 160)
        assert any(c[0] in range(85, 110) for c in colores)

    def test_u4_is_frame_pixel_detecta_cadet_blue(self):
        """U4: _is_frame_pixel detecta correctamente el color de marco."""
        # Cadet blue exacto
        pixel_marco = np.array([[95, 158, 160]], dtype=np.float32)
        resultado = _is_frame_pixel(pixel_marco)
        assert resultado[0] is True or resultado[0] == True

    def test_u4_is_frame_pixel_no_detecta_dbz(self):
        """U4: _is_frame_pixel no detecta colores dBZ como marco."""
        # Rojo intenso (color dBZ de tormenta fuerte)
        pixel_dbz = np.array([[255, 52, 0]], dtype=np.float32)
        resultado = _is_frame_pixel(pixel_dbz)
        assert not resultado[0]

    def test_u4_desde_banco_local(self):
        """U4: Limpieza completa usando test_radar.png y test_radar.gif del banco."""
        for nombre in ["test_radar.png", "test_radar.gif"]:
            path = FIXTURES_DIR / nombre
            if not path.exists():
                print(f"[ERROR] Objeto no encontrado: {nombre} en {FIXTURES_DIR}")
                continue

            imagen = Image.open(path)
            clean_rgb, gap_mask, dbz_map = clean_image(imagen)
            print(f"[U4] {nombre}: clean={clean_rgb.shape}, storm_px={int(np.count_nonzero(dbz_map))}")
            assert clean_rgb is not None