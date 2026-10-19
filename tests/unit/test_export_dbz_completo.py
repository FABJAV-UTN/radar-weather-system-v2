"""
Export dBZ completo — lo que entra al GeoTIFF.

Regresiones del 19/10/2026 (evento estratiforme del 13/10):
  1. La precipitación de 20 y 30 dBZ (verdes de la escala) debe llegar al TIF.
     Un filtro de "marca de agua" por color verde la borraba en toda la imagen.
  2. Los huecos cubiertos por la fase 5 (líneas de límites, rótulos) deben
     llegar al TIF: el orquestador exporta classify_array(filled_rgb), no el
     dBZ de la fase 4.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
import rasterio

from src.subsistema1 import geolocalizar as geo
from src.subsistema1.limpiar import DBZ_COLOR_MAP, classify_array
from src.subsistema1.rellenar import fill_gaps

DIR_TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
VARIANTE = "dacc_scheduler_560x741"

# Colores tal como los publica el GIF del DACC (ver limpiar.DBZ_COLOR_MAP).
VERDE_20 = DBZ_COLOR_MAP[20]
VERDE_30 = DBZ_COLOR_MAP[30]


@pytest.fixture(scope="module")
def geometrias():
    return geo.cargar_geometrias(DIR_TEMPLATES / geo.NOMBRE_GEOMETRIAS)


def _leer_banda(geotiff_bytes: bytes) -> np.ndarray:
    with rasterio.MemoryFile(io.BytesIO(geotiff_bytes)) as mem, mem.open() as src:
        return src.read(1)


def test_geolocalizar_conserva_verdes_20_y_30_dbz(geometrias):
    """Un campo de lluvia verde (20 y 30 dBZ) sale completo en el GeoTIFF."""
    g = geometrias[VARIANTE]
    dbz = np.zeros((g.alto, g.ancho), dtype=np.int32)
    rgb = np.zeros((g.alto, g.ancho, 3), dtype=np.uint8)
    dbz[500:600, 250:350], rgb[500:600, 250:350] = 20, VERDE_20
    dbz[600:650, 250:350], rgb[600:650, 250:350] = 30, VERDE_30

    resultado = geo.geolocalizar(rgb, dbz, geometrias=geometrias, templates=[],
                                 crs_salida=None)
    banda = _leer_banda(resultado.geotiff_bytes)

    assert np.count_nonzero(banda == 20) == 100 * 100
    assert np.count_nonzero(banda == 30) == 50 * 100


def test_relleno_cubre_linea_divisoria_en_dbz_exportado():
    """Una línea de límite que corta un campo verde queda cubierta en el dBZ exportado."""
    clean_rgb = np.zeros((40, 40, 3), dtype=np.uint8)
    clean_rgb[5:35, 5:35] = VERDE_20
    clean_rgb[5:35, 20] = 0  # línea divisoria dibujada sobre la lluvia
    gap_mask = np.zeros((40, 40), dtype=bool)

    dbz_fase4 = classify_array(clean_rgb)
    dbz_relleno = classify_array(fill_gaps(clean_rgb, gap_mask))

    assert not dbz_fase4[5:35, 20].any(), "precondición: la línea es un hueco"
    # Los extremos de la línea (en el borde del campo) tienen pocos vecinos con
    # lluvia y el relleno los deja, a propósito; el tramo interior se cubre.
    assert (dbz_relleno[6:34, 20] == 20).all(), "el relleno no llegó al dBZ exportado"
    assert (dbz_relleno[5:35, 5:20] == 20).all(), "el relleno alteró píxeles válidos"
