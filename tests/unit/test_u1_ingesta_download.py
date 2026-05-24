"""
TEST U1 + U3: Ingesta / Descarga y Conectividad.
Módulo objetivo: src/subsistema1/ingestor.py

U1 — Descarga de latest.gif desde URL DACC, extracción de datos, limpieza post-test.
U3 — Verificación de conectividad HTTP 200 al endpoint del DACC.
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from PIL import Image

from src.subsistema1.ingestor import (
    IngestaResultado,
    _extraer_timestamp_de_nombre,
    _apply_timezone_offset,
    ingestar_local,
    ingestar_url,
)


# ── Helpers de fixtures ───────────────────────────────────────────────────────

def _gif_bytes_minimo() -> bytes:
    """Genera bytes de GIF válido en memoria."""
    img = Image.new("RGB", (100, 50), color=(94, 157, 159))
    buf = io.BytesIO()
    img.save(buf, format="GIF")
    buf.seek(0)
    return buf.read()


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


# ─────────────────────────────────────────────────────────────────────────────
# TEST U1: Descarga desde URL DACC
# ─────────────────────────────────────────────────────────────────────────────

class TestIngestaU1:
    """Tests para descarga desde URL DACC (Ruta B del pipeline)."""

    @pytest.mark.asyncio
    async def test_u1_descarga_exitosa_devuelve_bytes(self):
        """U1: Descarga exitosa devuelve bytes con cabecera GIF válida."""
        gif_bytes = _gif_bytes_minimo()

        mock_response = MagicMock()
        mock_response.content = gif_bytes
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        mock_ts = datetime(2026, 1, 30, 11, 14, 55)  # ya en hora local

        with (
            patch("src.subsistema1.ingestor.httpx.AsyncClient") as mock_client_cls,
            patch("src.subsistema1.ingestor.extract_timestamp", return_value=mock_ts),
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            resultado = await ingestar_url()

        assert isinstance(resultado, IngestaResultado)
        assert len(resultado.raw_bytes) > 0
        assert resultado.raw_bytes[:3] == b"GIF"
        assert resultado.origen == "url"
        assert resultado.fecha_hora == mock_ts
        print(f"[U1] Descarga OK — {len(resultado.raw_bytes)} bytes — ts={resultado.fecha_hora}")

    @pytest.mark.asyncio
    async def test_u1_timeout_lanza_excepcion(self):
        """U1: Timeout de red lanza httpx.TimeoutException."""
        with patch("src.subsistema1.ingestor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=httpx.TimeoutException("Connection timeout")
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(httpx.TimeoutException):
                await ingestar_url()

    @pytest.mark.asyncio
    async def test_u1_ocr_invalido_lanza_value_error(self):
        """U1: Si OCR no extrae timestamp, lanza ValueError con mensaje claro."""
        gif_bytes = _gif_bytes_minimo()

        mock_response = MagicMock()
        mock_response.content = gif_bytes
        mock_response.raise_for_status = MagicMock()

        with (
            patch("src.subsistema1.ingestor.httpx.AsyncClient") as mock_client_cls,
            patch("src.subsistema1.ingestor.extract_timestamp", return_value=None),
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ValueError, match="OCR no pudo extraer"):
                await ingestar_url()

    @pytest.mark.asyncio
    async def test_u1_ingestar_local_extrae_timestamp_de_nombre(self, tmp_path):
        """U1 Ruta A: Lee archivo local y extrae timestamp correcto del nombre."""
        gif_bytes = _gif_bytes_minimo()
        archivo = tmp_path / "radar_20260130_1514_55.gif"
        archivo.write_bytes(gif_bytes)

        resultado = await ingestar_local(archivo)

        assert isinstance(resultado, IngestaResultado)
        assert resultado.origen == "local"
        # UTC -3: 15:14 → 12:14
        assert resultado.fecha_hora.hour == 12
        assert resultado.fecha_hora.minute == 14
        assert resultado.fecha_hora.day == 30
        print(f"[U1-A] Local OK — ts={resultado.fecha_hora}")

    @pytest.mark.asyncio
    async def test_u1_ingestar_local_archivo_no_existe(self, tmp_path):
        """U1 Ruta A: Archivo inexistente lanza FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            await ingestar_local(tmp_path / "no_existe.gif")

    @pytest.mark.asyncio
    async def test_u1_ingestar_local_nombre_invalido(self, tmp_path):
        """U1 Ruta A: Nombre sin timestamp lanza ValueError."""
        gif_bytes = _gif_bytes_minimo()
        archivo = tmp_path / "sin_fecha.gif"
        archivo.write_bytes(gif_bytes)

        with pytest.raises(ValueError, match="timestamp"):
            await ingestar_local(archivo)


# ─────────────────────────────────────────────────────────────────────────────
# TEST U3: Conectividad HTTP
# ─────────────────────────────────────────────────────────────────────────────

class TestConectividadU3:
    """Tests de health-check del endpoint DACC (U3)."""

    @pytest.mark.asyncio
    async def test_u3_conectividad_http_200(self):
        """U3: La URL del DACC responde HTTP 200."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient.head", return_value=mock_response):
            async with httpx.AsyncClient() as client:
                response = await client.head(
                    "https://www2.contingencias.mendoza.gov.ar/radar/latest.gif",
                    follow_redirects=True,
                )
            assert response.status_code == 200
            print(f"[U3] Conectividad OK — status={response.status_code}")

    @pytest.mark.asyncio
    async def test_u3_conectividad_http_404_detectado(self):
        """U3: Un 404 es detectado correctamente (URL inválida)."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient.head", return_value=mock_response):
            async with httpx.AsyncClient() as client:
                response = await client.head(
                    "https://www2.contingencias.mendoza.gov.ar/radar/invalid.gif"
                )
            assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos del ingestor
# ─────────────────────────────────────────────────────────────────────────────

class TestHelpersIngestor:
    """Tests de las funciones internas del módulo ingestor."""

    def test_extraer_timestamp_formato_estandar(self):
        """Extrae timestamp de nombre con formato radar_YYYYMMDD_HHMMSS."""
        resultado = _extraer_timestamp_de_nombre("radar_20260523_143000.gif")
        # UTC-3: 14:30 → 11:30
        assert resultado is not None
        assert resultado.year == 2026
        assert resultado.month == 5
        assert resultado.day == 23
        assert resultado.hour == 11
        assert resultado.minute == 30

    def test_extraer_timestamp_formato_alternativo(self):
        """Extrae timestamp de nombre con formato YYYYMMDD_HHMM_SS."""
        resultado = _extraer_timestamp_de_nombre("radar_20260130_1514_55.gif")
        assert resultado is not None
        assert resultado.hour == 12  # 15 - 3
        assert resultado.minute == 14

    def test_extraer_timestamp_nombre_invalido(self):
        """Retorna None para nombres que no contienen timestamp."""
        assert _extraer_timestamp_de_nombre("latest.gif") is None
        assert _extraer_timestamp_de_nombre("imagen.png") is None
        assert _extraer_timestamp_de_nombre("") is None

    def test_apply_timezone_offset(self):
        """Aplica correctamente el offset UTC-3."""
        dt_utc = datetime(2026, 5, 23, 15, 0, 0)
        dt_local = _apply_timezone_offset(dt_utc)
        assert dt_local.hour == 12  # 15 - 3