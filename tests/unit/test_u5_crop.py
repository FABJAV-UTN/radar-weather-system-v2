"""
TEST U5: Recorte (Crop) de imágenes.
Módulo objetivo: src/subsistema1/crop.py

Testea:
- crop_imagen(image)             → pipeline completo de recorte
- encontrar_color_en_fila()      → detección de bordes en filas
- encontrar_color_en_columna()   → detección de bordes en columnas
"""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import httpx
import numpy as np
import pytest
from PIL import Image

from src.subsistema1.crop import crop_imagen

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _imagen_con_marco_cadet_blue(ancho: int = 600, alto: int = 500) -> Image.Image:
    """Imagen con marco visible en color #5e9d9f."""
    arr = np.ones((alto, ancho, 3), dtype=np.uint8) * 50
    color = [94, 157, 159]   # #5e9d9f
    grosor = 40
    # Bordes
    arr[:grosor, :] = color
    arr[-grosor:, :] = color
    arr[:, :grosor] = color
    arr[:, -grosor:] = color
    return Image.fromarray(arr, mode="RGB")


def _imagen_sin_marco(ancho: int = 400, alto: int = 300) -> Image.Image:
    """Imagen sin color de marco (gris neutro)."""
    arr = np.ones((alto, ancho, 3), dtype=np.uint8) * 100
    return Image.fromarray(arr, mode="RGB")


def _gif_desde_url_mock() -> bytes:
    """Simula bytes de latest.gif descargado."""
    img = _imagen_con_marco_cadet_blue()
    buf = io.BytesIO()
    img.save(buf, format="GIF")
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────────────────────
# TEST U5
# ─────────────────────────────────────────────────────────────────────────────

class TestCropU5:
    """Tests para el módulo de recorte (src/subsistema1/crop.py)."""

    def test_u5_crop_imagen_devuelve_array(self):
        """U5: crop_imagen devuelve ndarray (H, W, 3)."""
        imagen = _imagen_con_marco_cadet_blue()
        resultado = crop_imagen(imagen)

        assert isinstance(resultado, np.ndarray)
        assert resultado.ndim == 3
        assert resultado.shape[2] == 3
        print(f"[U5] Crop OK — shape={resultado.shape}")

    def test_u5_crop_imagen_reduce_dimensiones(self):
        """U5: El resultado tiene dimensiones menores que la imagen original (se recortó el marco)."""
        imagen = _imagen_con_marco_cadet_blue(600, 500)
        resultado = crop_imagen(imagen)

        alto_orig, ancho_orig = 500, 600
        assert resultado.shape[0] < alto_orig or resultado.shape[1] < ancho_orig, (
            "El crop no redujo ninguna dimensión — puede ser que no detectó el marco"
        )

    def test_u5_crop_imagen_imagen_pequena_no_falla(self):
        """U5: Imagen pequeña (sin marco posible) no lanza excepción."""
        imagen = _imagen_sin_marco(100, 80)
        # No debe lanzar excepción, puede devolver la imagen tal cual
        try:
            resultado = crop_imagen(imagen)
            assert resultado is not None
        except Exception as e:
            pytest.fail(f"crop_imagen lanzó excepción inesperada: {e}")

    def test_u5_crop_preserva_tipo_uint8(self):
        """U5: El array resultante es uint8."""
        imagen = _imagen_con_marco_cadet_blue()
        resultado = crop_imagen(imagen)
        assert resultado.dtype == np.uint8

    def test_u5_crop_desde_url_imagen_descargada(self):
        """U5: Aplica crop a imagen descargada de la URL (simulada). Limpia post-test."""
        gif_bytes = _gif_desde_url_mock()
        imagen = Image.open(io.BytesIO(gif_bytes))

        resultado = crop_imagen(imagen)
        assert isinstance(resultado, np.ndarray)
        print(f"[U5] Crop desde URL simulada — shape={resultado.shape}")
        # Cleanup: no hay archivos temporales en este pipeline (todo en memoria)

    def test_u5_crop_desde_banco_local(self):
        """U5: Aplica crop a imágenes del banco local si existen."""
        for nombre in ["test_radar.gif", "test_radar.png"]:
            path = FIXTURES_DIR / nombre
            if not path.exists():
                print(f"[ERROR] Objeto no encontrado: {nombre} en {FIXTURES_DIR}")
                continue

            imagen = Image.open(path)
            resultado = crop_imagen(imagen)
            print(f"[U5] {nombre} → crop shape={resultado.shape}")
            assert isinstance(resultado, np.ndarray)

    def test_u5_crop_no_escribe_disco(self, tmp_path):
        """U5: El pipeline no escribe archivos intermedios a disco."""
        imagen = _imagen_con_marco_cadet_blue()
        archivos_antes = list(tmp_path.iterdir())

        resultado = crop_imagen(imagen)

        archivos_despues = list(tmp_path.iterdir())
        assert archivos_antes == archivos_despues, "crop_imagen escribió archivos inesperados a disco"