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
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-para-tests-minimo-32-chars")

try:
    import rasterio
    from rasterio.crs import CRS
    from rasterio.transform import Affine
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

from src.subsistema1.geolocalizar import (
    _apply_dbz_filters,
    correct_transform,
    extract_shape_mask,
    get_center_geo,
    match_template_binary,
    pixel_to_geo,
    dbz_array_to_geotiff_bytes,
    refine_subpixel_peak,
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
        """U7: match_template_binary devuelve ((col, fila), score, method)."""
        image_mask = np.zeros((100, 100), dtype=np.uint8)
        image_mask[20:40, 20:40] = 255  # patrón en posición conocida

        template_mask = np.zeros((20, 20), dtype=np.uint8)
        template_mask[:, :] = 255

        (col, fila), score, method = match_template_binary(image_mask, template_mask)

        assert isinstance(col, int)
        assert isinstance(fila, int)
        assert isinstance(score, float)
        assert isinstance(method, str)
        assert 0.0 <= score <= 1.0
        print(f"[U7] Match: ({col}, {fila}), score={score:.4f}, method={method}")

    def test_u7_match_encuentra_posicion_correcta(self):
        """U7: El match devuelve una posición y score válidos."""
        image_mask = np.zeros((200, 200), dtype=np.uint8)
        # Patrón cuadrado en posición (50, 30)
        image_mask[30:60, 50:80] = 255

        template_mask = np.zeros((30, 30), dtype=np.uint8)
        template_mask[:, :] = 255

        (col, fila), score, method = match_template_binary(image_mask, template_mask)

        assert isinstance(col, int) and isinstance(fila, int)
        assert fila == 30
        assert 0 <= col <= 50
        assert score > 0.4
        assert "confirmed" in method or "best" in method

    def test_u7_match_score_minimo_en_imagen_vacia(self):
        """U7: En imagen vacía vs template lleno, no hay confirmación strict."""
        image_mask = np.zeros((100, 100), dtype=np.uint8)
        template_mask = np.ones((20, 20), dtype=np.uint8) * 255

        (col, fila), score, method = match_template_binary(image_mask, template_mask)
        assert "confirmed" not in method


class TestRefineSubpixelPeak:
    """Tests para refinamiento subpíxel."""

    def test_u7_refine_subpixel_pico_simetrico_no_cambia(self):
        """U7: Si los vecinos son simétricos, el pico se mantiene en el entero exacto."""
        # Pico en (row=1, col=1) con vecinos simétricos
        rmap = np.array([
            [0.5, 0.8, 0.5],
            [0.8, 1.0, 0.8],
            [0.5, 0.8, 0.5],
        ], dtype=np.float32)
        sub_c, sub_r = refine_subpixel_peak(rmap, col=1, row=1)
        assert abs(sub_c - 1.0) < 1e-6
        assert abs(sub_r - 1.0) < 1e-6

    def test_u7_refine_subpixel_sesgo_derecha(self):
        """U7: Si el vecino derecho es mayor que el izquierdo, el pico se desplaza a la derecha."""
        rmap = np.array([
            [0.4, 0.7, 0.5],
            [0.6, 1.0, 0.9],  # derecha (0.9) > izquierda (0.6)
            [0.4, 0.7, 0.5],
        ], dtype=np.float32)
        sub_c, sub_r = refine_subpixel_peak(rmap, col=1, row=1)
        assert sub_c > 1.0  # desplazado a la derecha
        assert sub_c < 1.5
        assert abs(sub_r - 1.0) < 1e-6


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
                assert src.dtypes[0] == "uint8"
                assert src.nodata == 0
                assert src.crs.to_epsg() == 4326
        print("[U7] GeoTIFF 1 banda dBZ ✓")

    def test_u7_dbz_geotiff_valores_correctos(self):
        """U7: Los valores dBZ (incluyendo 10, 20 y 30 dBZ) se preservan en el GeoTIFF."""
        dbz_array = np.zeros((50, 50), dtype=np.uint8)
        dbz_array[5:10, 5:10] = 10    # dBZ = 10
        dbz_array[10:15, 10:15] = 20  # dBZ = 20
        dbz_array[15:20, 15:20] = 30  # dBZ = 30
        dbz_array[20:30, 20:30] = 45  # dBZ = 45
        dbz_array[30:35, 30:35] = 60  # dBZ = 60

        transform = Affine(0.01, 0, -70.0, 0, -0.01, -32.0)
        crs = CRS.from_epsg(4326)

        tiff_bytes = dbz_array_to_geotiff_bytes(dbz_array, transform, crs)

        with rasterio.io.MemoryFile(tiff_bytes) as memfile:
            with memfile.open() as src:
                band = src.read(1)
                unique = set(np.unique(band))
                assert 0 in unique
                assert 10 in unique
                assert 20 in unique
                assert 30 in unique
                assert 45 in unique
                assert 60 in unique
        print("[U7] Valores dBZ (10, 20, 30, 45, 60) preservados ✓")

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


# ─────────────────────────────────────────────────────────────────────────────
# TEST U7: Filtros dBZ
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyDBZFilters:
    """Tests para la función _apply_dbz_filters."""

    def test_u7_apply_dbz_filters_preserva_10_20_30_dbz(self):
        """U7: _apply_dbz_filters preserva reflectividades 10, 20 y 30 dBZ."""
        dbz_map = np.zeros((10, 10), dtype=np.int32)
        dbz_map[1, 1] = 10
        dbz_map[2, 2] = 20
        dbz_map[3, 3] = 30
        dbz_map[4, 4] = 35
        dbz_map[5, 5] = 54

        filled_rgb = np.zeros((10, 10, 3), dtype=np.uint8)

        resultado = _apply_dbz_filters(dbz_map, filled_rgb)

        assert resultado[1, 1] == 10, f"10 dBZ fue alterado: {resultado[1, 1]}"
        assert resultado[2, 2] == 20, f"20 dBZ fue alterado: {resultado[2, 2]}"
        assert resultado[3, 3] == 30, f"30 dBZ fue alterado: {resultado[3, 3]}"
        assert resultado[4, 4] == 35, f"35 dBZ fue alterado: {resultado[4, 4]}"
        assert resultado[5, 5] == 54, f"54 dBZ fue alterado: {resultado[5, 5]}"
        assert resultado[0, 0] == 0, f"0 dBZ (NoData) debe ser 0: {resultado[0, 0]}"

    def test_u7_apply_dbz_filters_descarta_menores_a_10(self):
        """U7: _apply_dbz_filters descarta valores < 10 dBZ pero no 10, 20 ni 30."""
        dbz_map = np.zeros((5, 5), dtype=np.int32)
        dbz_map[0, 0] = 5   # Menor a 10 dBZ
        dbz_map[1, 1] = 10  # 10 dBZ válido
        filled_rgb = np.zeros((5, 5, 3), dtype=np.uint8)

        resultado = _apply_dbz_filters(dbz_map, filled_rgb)

        assert resultado[0, 0] == 0, f"Valores < 10 dBZ deben descartarse a 0: {resultado[0, 0]}"
        assert resultado[1, 1] == 10, f"10 dBZ debe conservarse: {resultado[1, 1]}"

    def test_u7_apply_dbz_filters_filtra_clutter_y_watermark(self):
        """U7: _apply_dbz_filters enmascara correctamente clutter_mask y marca de agua verde."""
        dbz_map = np.full((10, 10), 45, dtype=np.int32)
        filled_rgb = np.zeros((10, 10, 3), dtype=np.uint8)

        # Píxel de watermark verde en (2, 2): g > r + 15, g > b + 15, 50 <= g <= 140
        filled_rgb[2, 2] = [20, 100, 20]

        # Eco fijo en clutter_mask en (3, 3)
        clutter_mask = np.zeros((10, 10), dtype=bool)
        clutter_mask[3, 3] = True

        resultado = _apply_dbz_filters(dbz_map, filled_rgb, clutter_mask)

        assert resultado[2, 2] == 0, "Píxel de watermark no fue puesto a 0"
        assert resultado[3, 3] == 0, "Píxel de clutter_mask no fue puesto a 0"
        assert resultado[5, 5] == 45, "Píxel válido fue alterado incorrectamente"


# ─────────────────────────────────────────────────────────────────────────────
# TEST U7: Pipeline completo
# ─────────────────────────────────────────────────────────────────────────────

class TestGeolocalizar:
    """Tests del pipeline completo de geolocalización."""

    def test_u7_geolocalizar_con_templates_mock(self):
        """U7: geolocalizar genera GeoResultado con bytes de GeoTIFF 1 banda dBZ y preserva 10-30 dBZ."""
        from src.subsistema1.geolocalizar import geolocalizar, GeoResultado

        filled_rgb = np.zeros((200, 200, 3), dtype=np.uint8)
        # Dibujar una forma para template matching
        filled_rgb[30:50, 30:50] = 200

        dbz_map = np.zeros((200, 200), dtype=np.int32)
        dbz_map[10:20, 10:20] = 10  # 10 dBZ
        dbz_map[20:30, 20:30] = 20  # 20 dBZ
        dbz_map[30:40, 30:40] = 30  # 30 dBZ
        dbz_map[50:150, 50:150] = 45  # 45 dBZ

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
        mock_eco_src.crs = mock_crs
        mock_eco_src.width = 20
        mock_eco_src.height = 20
        mock_eco_src.read = MagicMock(return_value=np.moveaxis(eco_arr, -1, 0))

        orig_open = rasterio.open
        def mock_open(file, *args, **kwargs):
            if file == Path("/mock/eco.tif") or str(file).endswith("eco.tif") or "eco" in str(file):
                return mock_eco_src
            return orig_open(file, *args, **kwargs)

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("src.subsistema1.geolocalizar._get_eco_template_paths",
                  return_value=[Path("/mock/eco.tif")]),
            patch("src.subsistema1.geolocalizar.rasterio.open", side_effect=mock_open),
        ):
            resultado = geolocalizar(filled_rgb, dbz_map)

        assert isinstance(resultado, GeoResultado)
        assert len(resultado.geotiff_bytes) > 0
        assert isinstance(resultado.score_match, float)
        assert isinstance(resultado.transform_affine, str)
        assert resultado.dbz_array is not None
        # Validar que los valores 10, 20 y 30 dBZ se mantienen en dbz_array
        assert resultado.dbz_array[15, 15] == 10
        assert resultado.dbz_array[25, 25] == 20
        assert resultado.dbz_array[35, 35] == 30
        assert resultado.dbz_array[100, 100] == 45

        # Verificar que es un GeoTIFF de 1 banda
        with rasterio.io.MemoryFile(resultado.geotiff_bytes) as memfile:
            with memfile.open() as src:
                assert src.count == 1
                assert src.dtypes[0] == "uint8"
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
        dbz_map[20:40, 20:40] = 20  # 20 dBZ
        dbz_map[50:150, 50:150] = 45

        eco_path = FIXTURES_DIR / "template_eco_fijo.tif"
        with patch("src.subsistema1.geolocalizar._get_eco_template_paths", return_value=[eco_path]):
            resultado = geolocalizar(filled_rgb, dbz_map)

        print(f"[U7] Banco local OK — score={resultado.score_match:.4f}")
        assert resultado.score_match >= 0.0
        # Verificar que es 1 banda
        with rasterio.io.MemoryFile(resultado.geotiff_bytes) as memfile:
            with memfile.open() as src:
                assert src.count == 1

    def test_u7_geolocalizar_calculo_directo_affine(self):
        """U7: Verifica que el origen del Affine Transform se calcula directamente desde el eco."""
        from src.subsistema1.geolocalizar import geolocalizar

        # Imagen 100x100 con eco centrado en (col 40, row 30)
        filled_rgb = np.zeros((100, 100, 3), dtype=np.uint8)
        filled_rgb[30:50, 40:60] = 200
        dbz_map = np.zeros((100, 100), dtype=np.int32)
        dbz_map[30:50, 40:60] = 45

        mock_transform = Affine(0.01, 0.0, -68.80, 0.0, -0.01, -32.90)
        mock_crs = CRS.from_epsg(4326)

        eco_arr = np.ones((20, 20, 3), dtype=np.uint8) * 200
        mock_eco_src = MagicMock()
        mock_eco_src.__enter__ = MagicMock(return_value=mock_eco_src)
        mock_eco_src.__exit__ = MagicMock(return_value=False)
        mock_eco_src.transform = mock_transform
        mock_eco_src.crs = mock_crs
        mock_eco_src.width = 20
        mock_eco_src.height = 20
        mock_eco_src.read = MagicMock(return_value=np.moveaxis(eco_arr, -1, 0))

        orig_open = rasterio.open
        def mock_open(file, *args, **kwargs):
            if file == Path("/mock/eco.tif") or "eco" in str(file):
                return mock_eco_src
            return orig_open(file, *args, **kwargs)

        with (
            patch("src.subsistema1.geolocalizar._get_eco_template_paths", return_value=[Path("/mock/eco.tif")]),
            patch("src.subsistema1.geolocalizar.rasterio.open", side_effect=mock_open),
        ):
            resultado = geolocalizar(filled_rgb, dbz_map)

        with rasterio.io.MemoryFile(resultado.geotiff_bytes) as memfile:
            with memfile.open() as src:
                # El centro del eco está en pixel (9.5, 9.5) del template:
                # true_x = -68.80 + 9.5 * 0.01 = -68.705
                # true_y = -32.90 + 9.5 * (-0.01) = -32.995
                # El match cayó en (col 40, row 30), centro en imagen = (49.5, 39.5)
                # origin_x = -68.705 - (49.5 * 0.01) = -68.705 - 0.495 = -69.20
                # origin_y = -32.995 - (39.5 * -0.01) = -32.995 + 0.395 = -32.60
                assert abs(src.transform.c - (-69.20)) < 1e-6
                assert abs(src.transform.f - (-32.60)) < 1e-6
                assert abs(src.transform.a - 0.01) < 1e-6
                assert abs(src.transform.e - (-0.01)) < 1e-6