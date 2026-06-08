"""
TEST U7: Georreferenciación.
Módulo objetivo: src/subsistema1/geolocalizar.py

Testea:
- match_template_binary(image_mask, template_mask) → template matching TM_CCOEFF_NORMED
- correct_transform(transform, delta_lon, delta_lat) → corrección del Affine Transform
- extract_shape_mask(arr)                           → extracción de máscara de forma
- dbz_array_to_geotiff_bytes(dbz_array, ...)         → GeoTIFF 1 banda dBZ
- geolocalizar(filled_rgb, dbz_map)                  → pipeline completo
"""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

try:
    import rasterio
    from rasterio.crs import CRS
    from rasterio.transform import Affine
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

from src.subsistema1.geolocalizar import (
    correct_transform,
    extract_shape_mask,
    get_center_geo,
    match_template_binary,
    pixel_to_geo,
    dbz_array_to_geotiff_bytes,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

pytestmark = pytest.mark.skipif(not HAS_RASTERIO, reason="rasterio no disponible")


# ─────────────────────────────────────────────────────────────────────────────
# TEST U7: Helpers internos
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractShapeMask:
    """Tests para extract_shape_mask."""

    def test_u7_mascara_rgb_canal_mayor_threshold(self):
        """U7: Píxeles con algún canal > 10 → máscara=255."""
        arr = np.zeros((10, 10, 3), dtype=np.uint8)
        arr[3:7, 3:7, 0] = 50  # región con dato
        mask = extract_shape_mask(arr, threshold=10)
        assert mask.shape == (10, 10)
        assert mask[5, 5] == 255
        assert mask[0, 0] == 0

    def test_u7_mascara_rgba_usa_canal_alpha(self):
        """U7: Para RGBA, usa el canal alpha para la máscara."""
        arr = np.zeros((10, 10, 4), dtype=np.uint8)
        arr[2:8, 2:8, 3] = 200  # alpha alta en el centro
        mask = extract_shape_mask(arr, threshold=10)
        assert mask[5, 5] == 255
        assert mask[0, 0] == 0

    def test_u7_mascara_2d(self):
        """U7: Array 2D (escala de grises) también funciona."""
        arr = np.zeros((10, 10), dtype=np.uint8)
        arr[4:6, 4:6] = 100
        mask = extract_shape_mask(arr, threshold=10)
        assert mask[5, 5] == 255
        assert mask[0, 0] == 0


class TestMatchTemplateBinary:
    """Tests para match_template_binary."""

    def test_u7_match_devuelve_tupla_posicion_score(self):
        """U7: match_template_binary devuelve ((col, fila), score)."""
        image_mask = np.zeros((100, 100), dtype=np.uint8)
        image_mask[20:40, 20:40] = 255  # patrón en posición conocida

        template_mask = np.zeros((20, 20), dtype=np.uint8)
        template_mask[:, :] = 255

        (col, fila), score = match_template_binary(image_mask, template_mask)

        assert isinstance(col, int)
        assert isinstance(fila, int)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0
        print(f"[U7] Match: ({col}, {fila}), score={score:.4f}")

    def test_u7_match_encuentra_posicion_correcta(self):
        """U7: El match encuentra la posición correcta del patrón."""
        image_mask = np.zeros((200, 200), dtype=np.uint8)
        # Patrón cuadrado en posición (50, 30)
        image_mask[30:60, 50:80] = 255

        template_mask = np.zeros((30, 30), dtype=np.uint8)
        template_mask[:, :] = 255

        (col, fila), score = match_template_binary(image_mask, template_mask)

        assert col == 50
        assert fila == 30
        assert score > 0.9

    def test_u7_match_score_minimo_en_imagen_vacia(self):
        """U7: En imagen vacía vs template lleno, score bajo."""
        image_mask = np.zeros((100, 100), dtype=np.uint8)
        template_mask = np.ones((20, 20), dtype=np.uint8) * 255

        _, score = match_template_binary(image_mask, template_mask)
        assert score < 0.5


class TestCorrectTransform:
    """Tests para correct_transform."""

    def test_u7_correct_transform_aplica_delta(self):
        """U7: correct_transform suma delta_lon y delta_lat al origen."""
        transform = Affine(0.01, 0, -70.0, 0, -0.01, -32.0)
        delta_lon = 0.05
        delta_lat = -0.03

        corregido = correct_transform(transform, delta_lon, delta_lat)

        # El nuevo origen debe ser c + delta_lon, f + delta_lat
        assert abs(corregido.c - (-70.0 + 0.05)) < 1e-9
        assert abs(corregido.f - (-32.0 - 0.03)) < 1e-9
        # Los coeficientes de escala no cambian
        assert corregido.a == transform.a
        assert corregido.e == transform.e

    def test_u7_correct_transform_delta_cero(self):
        """U7: Delta cero no cambia el transform."""
        transform = Affine(0.01, 0, -70.0, 0, -0.01, -32.0)
        corregido = correct_transform(transform, 0.0, 0.0)
        assert abs(corregido.c - transform.c) < 1e-9
        assert abs(corregido.f - transform.f) < 1e-9


class TestPixelToGeo:
    """Tests para pixel_to_geo y get_center_geo."""

    def test_u7_pixel_to_geo_origen(self):
        """U7: Píxel (0, 0) devuelve el origen del transform."""
        transform = Affine(0.01, 0, -70.0, 0, -0.01, -32.0)
        lon, lat = pixel_to_geo(transform, 0, 0)
        assert abs(lon - (-70.0)) < 1e-6
        assert abs(lat - (-32.0)) < 1e-6

    def test_u7_get_center_geo(self):
        """U7: El centro geográfico de un raster cuadrado está en el medio."""
        transform = Affine(0.01, 0, -70.0, 0, -0.01, -32.0)
        lon_centro, lat_centro = get_center_geo(transform, width=100, height=100)
        # Centro: píxel (49.5, 49.5)
        assert lon_centro > -70.0  # desplazado a la derecha
        assert lat_centro < -32.0  # desplazado hacia abajo


class TestDBZArrayToGeoTIFF:
    """Tests para dbz_array_to_geotiff_bytes (GeoTIFF 1 banda dBZ)."""

    def test_u7_dbz_geotiff_tiene_1_banda(self):
        """U7: GeoTIFF generado tiene exactamente 1 banda."""
        dbz_array = np.zeros((100, 100), dtype=np.uint8)
        dbz_array[40:60, 40:60] = 60  # Simular tormenta

        transform = Affine(0.01, 0, -70.0, 0, -0.01, -32.0)
        crs = CRS.from_epsg(4326)

        tiff_bytes = dbz_array_to_geotiff_bytes(dbz_array, transform, crs)
        assert len(tiff_bytes) > 0

        # Verificar con rasterio
        with rasterio.io.MemoryFile(tiff_bytes) as memfile:
            with memfile.open() as src:
                assert src.count == 1, f"Esperaba 1 banda, obtuve {src.count}"
                assert src.dtype == np.uint8
                assert src.nodata == 0
                assert src.crs.to_epsg() == 4326
        print("[U7] GeoTIFF 1 banda dBZ ✓")

    def test_u7_dbz_geotiff_valores_correctos(self):
        """U7: Los valores dBZ se preservan en el GeoTIFF."""
        dbz_array = np.zeros((50, 50), dtype=np.uint8)
        dbz_array[20:30, 20:30] = 45  # dBZ = 45
        dbz_array[10:15, 10:15] = 60  # dBZ = 60

        transform = Affine(0.01, 0, -70.0, 0, -0.01, -32.0)
        crs = CRS.from_epsg(4326)

        tiff_bytes = dbz_array_to_geotiff_bytes(dbz_array, transform, crs)

        with rasterio.io.MemoryFile(tiff_bytes) as memfile:
            with memfile.open() as src:
                band = src.read(1)
                unique = set(np.unique(band))
                assert 0 in unique
                assert 45 in unique
                assert 60 in unique
        print("[U7] Valores dBZ preservados ✓")

    def test_u7_dbz_geotiff_tags(self):
        """U7: El GeoTIFF tiene tags descriptivos."""
        dbz_array = np.zeros((50, 50), dtype=np.uint8)

        transform = Affine(0.01, 0, -70.0, 0, -0.01, -32.0)
        crs = CRS.from_epsg(4326)

        tiff_bytes = dbz_array_to_geotiff_bytes(dbz_array, transform, crs)

        with rasterio.io.MemoryFile(tiff_bytes) as memfile:
            with memfile.open() as src:
                tags = src.tags()
                assert "DESCRIPTION" in tags
                assert "UNIT" in tags
                assert "dBZ" in tags["UNIT"]
        print("[U7] Tags descriptivos presentes ✓")


class TestGeolocalizar:
    """Tests del pipeline completo de geolocalización."""

    def test_u7_geolocalizar_con_templates_mock(self):
        """U7: geolocalizar genera GeoResultado con bytes de GeoTIFF 1 banda dBZ."""
        from src.subsistema1.geolocalizar import geolocalizar, GeoResultado

        filled_rgb = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        dbz_map = np.zeros((200, 200), dtype=np.int32)
        dbz_map[50:150, 50:150] = 45  # Simular tormenta

        # Mock de los templates
        mock_transform = Affine(0.01, 0, -70.0, 0, -0.01, -32.0)
        mock_crs = CRS.from_epsg(4326)

        mock_geo_src = MagicMock()
        mock_geo_src.__enter__ = MagicMock(return_value=mock_geo_src)
        mock_geo_src.__exit__ = MagicMock(return_value=False)
        mock_geo_src.transform = mock_transform
        mock_geo_src.crs = mock_crs

        eco_arr = np.ones((20, 20, 3), dtype=np.uint8) * 200
        mock_eco_src = MagicMock()
        mock_eco_src.__enter__ = MagicMock(return_value=mock_eco_src)
        mock_eco_src.__exit__ = MagicMock(return_value=False)
        mock_eco_src.transform = mock_transform
        mock_eco_src.width = 20
        mock_eco_src.height = 20
        mock_eco_src.read = MagicMock(return_value=np.moveaxis(eco_arr, -1, 0))

        with (
            patch("src.subsistema1.geolocalizar.get_template_paths",
                  return_value=(Path("/mock/tif700.tif"), Path("/mock/eco.tif"))),
            patch("src.subsistema1.geolocalizar.rasterio.open",
                  side_effect=[mock_geo_src, mock_eco_src]),
        ):
            resultado = geolocalizar(filled_rgb, dbz_map)

        assert isinstance(resultado, GeoResultado)
        assert len(resultado.geotiff_bytes) > 0
        assert isinstance(resultado.score_match, float)
        assert isinstance(resultado.transform_affine, str)
        # Verificar que es un GeoTIFF de 1 banda
        with rasterio.io.MemoryFile(resultado.geotiff_bytes) as memfile:
            with memfile.open() as src:
                assert src.count == 1
                assert src.dtype == np.uint8
        print(f"[U7] GeoTIFF 1 banda dBZ generado — {len(resultado.geotiff_bytes)} bytes, score={resultado.score_match:.4f}")

    def test_u7_geolocalizar_desde_banco_local(self):
        """U7: Pipeline completo con template.png y template_eco_fijo.tif del banco."""
        from src.subsistema1.geolocalizar import geolocalizar

        fixtures_needed = ["template.png", "template_eco_fijo.tif"]
        for f in fixtures_needed:
            if not (FIXTURES_DIR / f).exists():
                print(f"[ERROR] Objeto no encontrado: {f} en {FIXTURES_DIR}")
                pytest.skip(f"Fixture {f} no encontrado en {FIXTURES_DIR}")

        from PIL import Image
        img_png = Image.open(FIXTURES_DIR / "template.png").convert("RGB")
        filled_rgb = np.array(img_png)
        # Crear dbz_map simulado
        dbz_map = np.zeros(filled_rgb.shape[:2], dtype=np.int32)
        dbz_map[50:150, 50:150] = 45

        with patch("src.subsistema1.geolocalizar.get_template_paths") as mock_paths:
            tif_name = "tif700.tif" if filled_rgb.shape[1] <= 799 else "tif800.tif"
            tif_path = FIXTURES_DIR.parent / "templates" / tif_name
            eco_path = FIXTURES_DIR / "template_eco_fijo.tif"

            if not tif_path.exists():
                pytest.skip(f"Template {tif_name} no encontrado")

            mock_paths.return_value = (tif_path, eco_path)
            resultado = geolocalizar(filled_rgb, dbz_map)

        print(f"[U7] Banco local OK — score={resultado.score_match:.4f}")
        assert resultado.score_match >= 0.0
        # Verificar que es 1 banda
        with rasterio.io.MemoryFile(resultado.geotiff_bytes) as memfile:
            with memfile.open() as src:
                assert src.count == 1