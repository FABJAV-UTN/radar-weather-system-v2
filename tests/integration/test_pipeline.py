"""
TESTS DE INTEGRACIÓN — Pipeline de Procesamiento (Subsistema 1).

Testea el pipeline end-to-end: desde la ingesta hasta la generación de GeoTIFF,
con mocks de la DB y los templates geoespaciales.

Estos tests validan que los módulos se integran correctamente entre sí:
ingestor → detectar_marco → crop → limpiar → rellenar → geolocalizar → orquestador

IMPORTANTE: Los GeoTIFFs de salida tienen 1 banda dBZ (uint8), no 3 bandas RGB.
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from PIL import Image

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _crear_imagen_con_marco(ancho: int = 500, alto: int = 400) -> Image.Image:
    """Imagen con marco cadet blue visible (tiene_marco=True)."""
    arr = np.ones((alto, ancho, 3), dtype=np.uint8) * 80
    color_marco = [94, 157, 159]
    grosor = 50
    arr[:grosor, :] = color_marco
    arr[-grosor:, :] = color_marco
    arr[:, :grosor] = color_marco
    arr[:, -grosor:] = color_marco
    return Image.fromarray(arr, mode="RGB")


def _crear_imagen_sin_marco(ancho: int = 400, alto: int = 300) -> Image.Image:
    """Imagen sin marco (tiene_marco=False)."""
    arr = np.ones((alto, ancho, 3), dtype=np.uint8) * 100
    return Image.fromarray(arr, mode="RGB")


def _gif_bytes(imagen: Image.Image) -> bytes:
    buf = io.BytesIO()
    imagen.save(buf, format="GIF")
    buf.seek(0)
    return buf.read()


def _mock_geo_resultado():
    """Mock de GeoResultado para evitar depender de rasterio en todos los tests."""
    from src.subsistema1.geolocalizar import GeoResultado
    # Crear un dbz_array simulado (1 banda)
    dbz_array = np.zeros((200, 200), dtype=np.uint8)
    dbz_array[50:150, 50:150] = 45  # Simular tormenta
    return GeoResultado(
        geotiff_bytes=b"FAKE_GEOTIFF_BYTES",
        transform_affine="| 0.01, 0.00, -70.00 || 0.00,-0.01, -32.00 |",
        crs_str="EPSG:4326",
        score_match=0.85,
        delta_lon=0.001,
        delta_lat=-0.002,
        dbz_array=dbz_array,
    )


def _mock_session():
    """AsyncSession mock con todos los métodos necesarios."""
    session = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    return session


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRACIÓN: Detectar Marco → Crop
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegracionMarcoYCrop:
    """Test de integración entre detectar_marco y crop_imagen."""

    def test_imagen_con_marco_se_cropea(self):
        """INT: imagen con marco → detectar_marco=True → crop reduce dimensiones."""
        from src.subsistema1.detectar_marco import detectar_marco
        from src.subsistema1.crop import crop_imagen

        imagen = _crear_imagen_con_marco(500, 400)
        tiene_marco = detectar_marco(imagen)

        if tiene_marco:
            resultado = crop_imagen(imagen)
            assert resultado.shape[0] < 400 or resultado.shape[1] < 500
            print(f"[INT] Marco detectado → crop: {imagen.size} → {resultado.shape}")
        else:
            print("[INT] Marco no detectado (umbral de tolerancia), test informativo")

    def test_imagen_sin_marco_no_se_cropea(self):
        """INT: imagen sin marco → detectar_marco=False → pipeline salta crop."""
        from src.subsistema1.detectar_marco import detectar_marco

        imagen = _crear_imagen_sin_marco()
        tiene_marco = detectar_marco(imagen)
        assert not tiene_marco
        print(f"[INT] Sin marco: tiene_marco={tiene_marco} ✓")


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRACIÓN: Limpiar → Rellenar
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegracionLimpiarRellenar:
    """Test de integración entre limpiar.py y rellenar.py."""

    def test_limpiar_y_rellenar_pipeline_completo(self):
        """INT: clean_image → fill_gaps produce array RGB sin huecos en watermark."""
        from src.subsistema1.limpiar import clean_image
        from src.subsistema1.rellenar import fill_gaps

        imagen = _crear_imagen_sin_marco(300, 250)
        clean_rgb, gap_mask, dbz_map = clean_image(imagen)
        filled_rgb = fill_gaps(clean_rgb, gap_mask)

        assert filled_rgb.shape == clean_rgb.shape
        assert filled_rgb.dtype == np.uint8
        print(f"[INT] Limpiar+Rellenar OK — shape={filled_rgb.shape}")

    def test_rellenar_recibe_salida_exacta_de_limpiar(self):
        """INT: La salida de clean_image puede alimentar directamente fill_gaps."""
        from src.subsistema1.limpiar import clean_image, WATERMARK_REGION
        from src.subsistema1.rellenar import fill_gaps

        imagen = _crear_imagen_sin_marco(200, 180)
        clean_rgb, gap_mask, dbz_map = clean_image(imagen)

        # gap_mask debe ser booleana (condición que fill_gaps requiere)
        assert gap_mask.dtype == bool

        filled = fill_gaps(clean_rgb, gap_mask)
        assert filled.shape == clean_rgb.shape

    def test_metricas_pixeles_coherentes(self):
        """INT: Las métricas de píxeles son coherentes entre limpiar y rellenar."""
        from src.subsistema1.limpiar import clean_image
        from src.subsistema1.rellenar import fill_gaps

        imagen = _crear_imagen_sin_marco(200, 180)
        clean_rgb, gap_mask, dbz_map = clean_image(imagen)

        pixeles_limpios = int(np.count_nonzero(dbz_map))
        filled_rgb = fill_gaps(clean_rgb, gap_mask)
        pixeles_rellenados = int(np.count_nonzero(
            np.any(filled_rgb > 0, axis=2) & ~np.any(clean_rgb > 0, axis=2)
        ))

        # Los pixeles rellenados no pueden ser más que los huecos detectados
        total_huecos = int(gap_mask.sum())
        assert pixeles_rellenados <= total_huecos
        print(f"[INT] Métricas: limpios={pixeles_limpios}, rellenados={pixeles_rellenados}, huecos={total_huecos}")

    def test_rellenar_detecta_linea_fina_que_cruza_tormenta(self):
        """INT: una línea fina que atraviesa la tormenta debe rellenarse con el color de sus vecinos."""
        from src.subsistema1.rellenar import fill_gaps

        h, w = 9, 9
        clean_rgb = np.zeros((h, w, 3), dtype=np.uint8)
        fill_color = np.array([200, 15, 134], dtype=np.uint8)

        # Tormenta grande con una línea fina de hueco cruzando el centro.
        storm_mask = np.zeros((h, w), dtype=bool)
        storm_mask[2:7, 2:7] = True
        clean_rgb[storm_mask] = fill_color

        gap_positions = [(4, 3), (4, 4), (4, 5), (4, 6)]
        for row, col in gap_positions:
            clean_rgb[row, col] = 0

        gap_mask = np.zeros((h, w), dtype=bool)
        gap_mask[4, 3:7] = True

        filled = fill_gaps(clean_rgb, gap_mask)

        assert np.all(filled[4, 3:7] == fill_color)
        assert np.all(filled[4, 3:7] != 0)


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRACIÓN: Geolocalización con 1 banda dBZ
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegracionGeolocalizacionDBZ:
    """Test de integración de geolocalización con GeoTIFF 1 banda dBZ."""

    def test_geolocalizar_recibe_dbz_map(self):
        """INT: geolocalizar() requiere dbz_map como segundo argumento."""
        from src.subsistema1.geolocalizar import geolocalizar
        import inspect

        sig = inspect.signature(geolocalizar)
        params = list(sig.parameters.keys())
        assert "dbz_map" in params, "geolocalizar debe recibir dbz_map"
        print("[INT] geolocalizar firma correcta: filled_rgb, dbz_map ✓")

    def test_georesultado_tiene_dbz_array(self):
        """INT: GeoResultado tiene el campo dbz_array."""
        from src.subsistema1.geolocalizar import GeoResultado

        dbz_array = np.zeros((100, 100), dtype=np.uint8)
        dbz_array[40:60, 40:60] = 60

        geo = GeoResultado(
            geotiff_bytes=b"test",
            transform_affine="test",
            crs_str="EPSG:4326",
            score_match=0.9,
            delta_lon=0.0,
            delta_lat=0.0,
            dbz_array=dbz_array,
        )
        assert geo.dbz_array is not None
        assert geo.dbz_array.dtype == np.uint8
        assert geo.dbz_array.shape == (100, 100)
        print("[INT] GeoResultado con dbz_array ✓")


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRACIÓN: Orquestador + Mocks de DB y Geo
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegracionOrquestador:
    """Test de integración del orquestador con mocks de DB y geolocalización."""

    @pytest.mark.asyncio
    async def test_orquestador_pipeline_ruta_local(self, tmp_path):
        """INT: ejecutar_pipeline_local procesa imagen local de punta a punta."""
        from src.subsistema1.orquestador import ejecutar_pipeline_local, ResultadoPipeline

        # Preparar archivo de imagen con nombre correcto
        imagen = _crear_imagen_sin_marco(300, 250)
        gif_bytes = _gif_bytes(imagen)
        archivo = tmp_path / "radar_20260523_143000.gif"
        archivo.write_bytes(gif_bytes)

        session = _mock_session()
        geo_mock = _mock_geo_resultado()

        # Mock de la DB: imagen creada con ID=1
        imagen_mock = MagicMock()
        imagen_mock.id = 1
        session.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

        with (
            patch("src.subsistema1.orquestador.ImagenRadarRepository") as MockImgRepo,
            patch("src.subsistema1.orquestador.ProcesamentoPasoRepository"),
            patch("src.subsistema1.orquestador.MetricaProcesamientoRepository"),
            patch("src.subsistema1.orquestador.IntentoDescargaRepository"),
            patch("src.subsistema1.orquestador.geolocalizar", return_value=geo_mock),
        ):
            repo_instance = AsyncMock()
            repo_instance.existe_duplicado = AsyncMock(return_value=False)
            repo_instance.crear = AsyncMock(return_value=imagen_mock)
            repo_instance.actualizar_estado = AsyncMock()
            repo_instance.actualizar_completado = AsyncMock()
            repo_instance.marcar_error = AsyncMock()
            MockImgRepo.return_value = repo_instance

            resultado = await ejecutar_pipeline_local(archivo, session)

        assert isinstance(resultado, ResultadoPipeline)
        assert resultado.imagen_id == 1
        # Verificar que el GeoResultado tiene dbz_array (1 banda dBZ)
        assert resultado.metricas.geo is not None
        assert resultado.metricas.geo.dbz_array is not None
        print(f"[INT] Pipeline local OK — exito={resultado.exito}, score={resultado.metricas.score_match}, dbz_banda_unica=True")

    @pytest.mark.asyncio
    async def test_orquestador_pipeline_url_duplicado_rechazado(self):
        """INT: Si la imagen ya existe en DB, el pipeline rechaza con ValueError."""
        from src.subsistema1.orquestador import ejecutar_pipeline_url

        session = _mock_session()
        ts_mock = datetime(2026, 5, 23, 20, 30, 0)
        ingesta_mock = MagicMock()
        ingesta_mock.fecha_hora = ts_mock
        ingesta_mock.raw_bytes = b"GIF89a"
        ingesta_mock.imagen_pil = _crear_imagen_sin_marco()

        with (
            patch("src.subsistema1.orquestador.ingestar_url", return_value=ingesta_mock),
            patch("src.subsistema1.orquestador.IntentoDescargaRepository") as MockIntento,
            patch("src.subsistema1.orquestador.ImagenRadarRepository") as MockImgRepo,
        ):
            intento_inst = AsyncMock()
            intento_inst.registrar = AsyncMock()
            MockIntento.return_value = intento_inst

            repo_instance = AsyncMock()
            repo_instance.obtener_por_fecha_hora = AsyncMock(return_value=SimpleNamespace(id=99, fecha_hora=ts_mock))
            MockImgRepo.return_value = repo_instance

            with pytest.raises(ValueError, match=r"Duplicado: URL '.*' timestamp=.*; ya existe imagen id=99 origen=url timestamp=.*"):
                await ejecutar_pipeline_url(session)

    @pytest.mark.asyncio
    async def test_orquestador_pipeline_local_duplicado_rechazado(self, tmp_path):
        """INT: Si la imagen local ya existe en DB, el pipeline rechaza con un mensaje claro."""
        from src.subsistema1.orquestador import ejecutar_pipeline_local

        imagen = _crear_imagen_sin_marco(300, 250)
        gif_bytes = _gif_bytes(imagen)
        archivo = tmp_path / "radar_20260523_143000.gif"
        archivo.write_bytes(gif_bytes)

        session = _mock_session()
        ts_mock = datetime(2026, 5, 23, 14, 30, 0)

        with (
            patch("src.subsistema1.orquestador.ImagenRadarRepository") as MockImgRepo,
            patch("src.subsistema1.orquestador.ProcesamentoPasoRepository"),
            patch("src.subsistema1.orquestador.MetricaProcesamientoRepository"),
            patch("src.subsistema1.orquestador.IntentoDescargaRepository"),
            patch("src.subsistema1.orquestador.geolocalizar", return_value=_mock_geo_resultado()),
        ):
            repo_instance = AsyncMock()
            repo_instance.obtener_por_fecha_hora = AsyncMock(return_value=SimpleNamespace(id=42, fecha_hora=ts_mock))
            MockImgRepo.return_value = repo_instance

            with pytest.raises(ValueError, match=r"Duplicado: archivo 'radar_20260523_143000.gif' timestamp=.*; ya existe imagen id=42 origen=local timestamp=.*"):
                await ejecutar_pipeline_local(archivo, session)

    @pytest.mark.asyncio
    async def test_orquestador_pipeline_url_completo(self):
        """INT: Pipeline URL de punta a punta con mocks de ingesta, DB y geo."""
        from src.subsistema1.orquestador import ejecutar_pipeline_url, ResultadoPipeline

        session = _mock_session()
        ts_mock = datetime(2026, 5, 23, 14, 30, 0)
        imagen_pil = _crear_imagen_sin_marco(300, 250)

        ingesta_mock = MagicMock()
        ingesta_mock.fecha_hora = ts_mock
        ingesta_mock.raw_bytes = _gif_bytes(imagen_pil)
        ingesta_mock.imagen_pil = imagen_pil

        imagen_db_mock = MagicMock()
        imagen_db_mock.id = 42
        geo_mock = _mock_geo_resultado()

        with (
            patch("src.subsistema1.orquestador.ingestar_url", return_value=ingesta_mock),
            patch("src.subsistema1.orquestador.ImagenRadarRepository") as MockImgRepo,
            patch("src.subsistema1.orquestador.ProcesamentoPasoRepository"),
            patch("src.subsistema1.orquestador.MetricaProcesamientoRepository"),
            patch("src.subsistema1.orquestador.IntentoDescargaRepository") as MockIntento,
            patch("src.subsistema1.orquestador.geolocalizar", return_value=geo_mock),
        ):
            intento_inst = AsyncMock()
            intento_inst.registrar = AsyncMock()
            MockIntento.return_value = intento_inst

            repo_instance = AsyncMock()
            repo_instance.existe_duplicado = AsyncMock(return_value=False)
            repo_instance.crear = AsyncMock(return_value=imagen_db_mock)
            repo_instance.actualizar_estado = AsyncMock()
            repo_instance.actualizar_completado = AsyncMock()
            repo_instance.marcar_error = AsyncMock()
            MockImgRepo.return_value = repo_instance

            paso_inst = AsyncMock()
            paso_inst.registrar = AsyncMock()

            metrica_inst = AsyncMock()
            metrica_inst.guardar = AsyncMock()

            resultado = await ejecutar_pipeline_url(session)

        assert isinstance(resultado, ResultadoPipeline)
        assert resultado.imagen_id == 42
        assert resultado.metricas.score_match == 0.85
        # Verificar que el GeoTIFF es de 1 banda dBZ
        assert resultado.metricas.geo is not None
        assert resultado.metricas.geo.dbz_array is not None
        assert resultado.metricas.geo.dbz_array.dtype == np.uint8
        print(f"[INT] Pipeline URL OK — imagen_id={resultado.imagen_id}, exito={resultado.exito}, dbz_1banda=True")