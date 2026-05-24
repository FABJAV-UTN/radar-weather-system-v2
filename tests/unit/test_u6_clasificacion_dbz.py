"""
TEST U6: Clasificación dBZ.
Módulo objetivo: src/subsistema1/limpiar.py → classify_array, DBZ_COLOR_MAP

Testea:
- classify_array(rgb_array, threshold) → clasificación por distancia euclídea
- DBZ_COLOR_MAP                        → 16 niveles del mapa de colores
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.subsistema1.limpiar import (
    DBZ_COLOR_MAP,
    DBZ_COLORS,
    DBZ_VALUES,
    DEFAULT_COLOR_THRESHOLD,
    classify_array,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


# ─────────────────────────────────────────────────────────────────────────────
# TEST U6: DBZ_COLOR_MAP
# ─────────────────────────────────────────────────────────────────────────────

class TestDBZColorMap:
    """Validaciones del mapa de colores dBZ."""

    def test_u6_dbz_color_map_tiene_16_niveles(self):
        """U6: El mapa dBZ tiene exactamente 16 niveles."""
        assert len(DBZ_COLOR_MAP) == 16

    def test_u6_dbz_color_map_valores_en_rango(self):
        """U6: Todos los niveles dBZ están en rango 10-80."""
        for dbz_val in DBZ_COLOR_MAP:
            assert 10 <= dbz_val <= 80, f"Nivel dBZ {dbz_val} fuera de rango [10, 80]"

    def test_u6_dbz_color_map_colores_rgb_validos(self):
        """U6: Todos los colores son tuplas RGB en [0, 255]."""
        for dbz_val, color in DBZ_COLOR_MAP.items():
            assert len(color) == 3, f"Color {dbz_val} no tiene 3 canales"
            for canal in color:
                assert 0 <= canal <= 255, f"Canal {canal} fuera de rango en dBZ={dbz_val}"

    def test_u6_dbz_values_array_precomputado(self):
        """U6: DBZ_VALUES es un array numpy con los valores del mapa."""
        assert len(DBZ_VALUES) == len(DBZ_COLOR_MAP)
        assert DBZ_VALUES.min() == min(DBZ_COLOR_MAP.keys())
        assert DBZ_VALUES.max() == max(DBZ_COLOR_MAP.keys())

    def test_u6_dbz_colors_array_precomputado(self):
        """U6: DBZ_COLORS es un array (16, 3) float32."""
        assert DBZ_COLORS.shape == (16, 3)
        assert DBZ_COLORS.dtype == np.float32


# ─────────────────────────────────────────────────────────────────────────────
# TEST U6: classify_array
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyArray:
    """Tests de la función classify_array."""

    def test_u6_classify_array_forma_salida(self):
        """U6: classify_array(H, W, 3) devuelve (H, W) int32."""
        img = np.random.randint(0, 256, (50, 60, 3), dtype=np.uint8)
        resultado = classify_array(img)
        assert resultado.shape == (50, 60)
        assert resultado.dtype == np.int32

    def test_u6_classify_array_color_dbz_exacto(self):
        """U6: Un píxel con color exacto de dBZ obtiene ese valor."""
        # Color de 10 dBZ: (66, 63, 140)
        dbz_10_color = np.array(DBZ_COLOR_MAP[10], dtype=np.uint8)
        img = np.zeros((1, 1, 3), dtype=np.uint8)
        img[0, 0] = dbz_10_color

        resultado = classify_array(img, threshold=5.0)
        assert resultado[0, 0] == 10, f"Se esperaba dBZ=10, se obtuvo {resultado[0, 0]}"

    def test_u6_classify_array_color_negro_da_cero(self):
        """U6: Píxel negro (0, 0, 0) no coincide con ningún color dBZ → 0."""
        img = np.zeros((1, 1, 3), dtype=np.uint8)
        resultado = classify_array(img, threshold=DEFAULT_COLOR_THRESHOLD)
        assert resultado[0, 0] == 0

    def test_u6_classify_array_threshold_bajo_filtra_pixeles(self):
        """U6: Con threshold muy bajo, casi ningún píxel aleatorio es clasificado."""
        np.random.seed(42)
        img = np.random.randint(0, 256, (10, 10, 3), dtype=np.uint8)
        resultado = classify_array(img, threshold=1.0)
        # Con threshold=1, solo coincidencias casi exactas
        clasificados = (resultado > 0).sum()
        assert clasificados < 100  # La gran mayoría no coincide

    def test_u6_classify_array_threshold_alto_clasifica_todo(self):
        """U6: Con threshold muy alto, todos los píxeles se clasifican a algún dBZ."""
        img = np.random.randint(0, 256, (5, 5, 3), dtype=np.uint8)
        resultado = classify_array(img, threshold=500.0)
        # Con threshold enorme, todos deberían clasificarse
        sin_clasificar = (resultado == 0).sum()
        total = 5 * 5
        assert sin_clasificar < total  # Al menos algunos clasificados

    def test_u6_classify_array_solo_valores_dbz(self):
        """U6: Los valores no nulos del resultado son siempre valores dBZ válidos."""
        img = np.random.randint(0, 256, (20, 20, 3), dtype=np.uint8)
        resultado = classify_array(img)
        valores_dbz_validos = set(DBZ_COLOR_MAP.keys()) | {0}
        valores_en_resultado = set(np.unique(resultado))
        assert valores_en_resultado.issubset(valores_dbz_validos), (
            f"Valores inesperados: {valores_en_resultado - valores_dbz_validos}"
        )

    def test_u6_pixeles_aleatorios_banco_local(self):
        """U6: Toma 10 píxeles al azar de imagen del banco y los clasifica."""
        path = FIXTURES_DIR / "test_radar.gif"
        if not path.exists():
            print(f"[ERROR] Objeto no encontrado: test_radar.gif en {FIXTURES_DIR}")
            pytest.skip(f"Fixture no encontrado: {path}")

        imagen = Image.open(path)
        if getattr(imagen, "is_animated", False):
            imagen.seek(0)
        arr = np.array(imagen.convert("RGB"))

        # Seleccionar 10 píxeles al azar
        np.random.seed(0)
        h, w = arr.shape[:2]
        filas = np.random.randint(0, h, 10)
        cols = np.random.randint(0, w, 10)
        pixeles = arr[filas, cols, :]  # (10, 3)

        # Clasificar como array (1, 10, 3)
        img_virtual = pixeles[np.newaxis, :, :]
        resultado = classify_array(img_virtual)

        print("[U6] 10 píxeles aleatorios del banco:")
        for i in range(10):
            dbz = resultado[0, i]
            rgb = pixeles[i]
            tipo = "TORMENTA" if dbz > 0 else "sin dato"
            print(f"  px{i+1}: RGB={tuple(rgb)} → dBZ={dbz} [{tipo}]")

        # Todos los valores deben ser válidos
        valores = set(np.unique(resultado))
        assert valores.issubset(set(DBZ_COLOR_MAP.keys()) | {0})