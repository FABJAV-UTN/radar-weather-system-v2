"""
TEST U5: Relleno de huecos e inpainting.
Módulo objetivo: src/subsistema1/rellenar.py

Testea:
- fill_gaps(clean_rgb, gap_mask)   → pipeline completo de inpainting
- _detect_thin_gaps()               → detección de líneas/grietas delgadas
- _fill_internal_holes()           → relleno de huecos internos de tormenta
"""
from __future__ import annotations

import numpy as np
import pytest

from src.subsistema1.rellenar import (
    fill_gaps,
    _detect_thin_gaps,
    _fill_internal_holes,
    _fill_watermark_region,
)


class TestRellenoU5:
    """Tests para el módulo de inpainting/relleno (src/subsistema1/rellenar.py)."""

    def test_u5_fill_gaps_preserva_dimensiones_y_tipo(self):
        """U5: fill_gaps preserva shape y tipo uint8."""
        clean_rgb = np.zeros((100, 100, 3), dtype=np.uint8)
        clean_rgb[20:80, 20:80] = [200, 100, 50]
        gap_mask = np.zeros((100, 100), dtype=bool)
        gap_mask[30:40, 30:40] = True

        filled = fill_gaps(clean_rgb, gap_mask)

        assert isinstance(filled, np.ndarray)
        assert filled.shape == clean_rgb.shape
        assert filled.dtype == np.uint8

    def test_u5_fill_gaps_rellena_hueco_interno(self):
        """U5: fill_gaps rellena un hueco cerrado dentro de la tormenta."""
        clean_rgb = np.zeros((50, 50, 3), dtype=np.uint8)
        # Bloque de tormenta color [100, 150, 200]
        clean_rgb[10:40, 10:40] = [100, 150, 200]
        # Hueco interno en (20:25, 20:25)
        clean_rgb[20:25, 20:25] = [0, 0, 0]

        gap_mask = np.zeros((50, 50), dtype=bool)

        filled = fill_gaps(clean_rgb, gap_mask, fill_general_holes=True)

        # El hueco interno debe haber sido rellenado
        assert np.all(filled[22, 22] > 0)
        assert np.array_equal(filled[22, 22], [100, 150, 200])

    def test_u5_detect_thin_gaps(self):
        """U5: _detect_thin_gaps detecta píxeles sin dato rodeados de tormenta."""
        storm_mask = np.ones((10, 10), dtype=bool)
        # Línea de 1 pixel sin dato
        storm_mask[5, 2:8] = False

        thin_gaps = _detect_thin_gaps(storm_mask, min_storm_neighbors=5)
        assert np.any(thin_gaps[5, 2:8])
