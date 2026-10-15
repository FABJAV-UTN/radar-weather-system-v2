"""
U1b — Validación de la descarga y reintentos (ingestar_url).

La madrugada del 13/10/2026 muchos GIF llegaron cortados ("image file is
truncated") o no eran imagen ("cannot identify image file"). Ahora la descarga
se valida y, si llegó mal, se reintenta hasta DESCARGA_INTENTOS veces.
"""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from src.subsistema1 import ingestor
from src.subsistema1.ingestor import (
    DescargaIncompletaError,
    ingestar_url,
    validar_imagen_descargada,
)


def _gif(alto: int = 741, ancho: int = 560) -> bytes:
    """GIF con ruido (no se comprime a casi nada, así un recorte se nota)."""
    arr = np.random.default_rng(0).integers(0, 255, (alto, ancho, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="GIF")
    return buf.getvalue()


GIF_OK = _gif()
GIF_CORTADO = GIF_OK[:-83]          # como en el log: "(83 bytes not processed)"
NO_IMAGEN = b"<html><body>502 Bad Gateway</body></html>"


def _respuesta(contenido: bytes, headers: dict | None = None):
    r = MagicMock()
    r.content = contenido
    r.status_code = 200
    r.raise_for_status = MagicMock()
    r.headers = headers if headers is not None else {}
    return r


def _cliente(*respuestas):
    cliente = AsyncMock()
    cliente.get = AsyncMock(side_effect=list(respuestas))
    cliente.__aenter__ = AsyncMock(return_value=cliente)
    cliente.__aexit__ = AsyncMock(return_value=False)
    return cliente


# ── validar_imagen_descargada ─────────────────────────────────────────────────

def test_u1b_valida_gif_completo():
    assert validar_imagen_descargada(GIF_OK) is None


@pytest.mark.parametrize("bytes_faltantes", [3, 35, 83, 242])
def test_u1b_detecta_gif_cortado(bytes_faltantes):
    assert "incompleta" in validar_imagen_descargada(GIF_OK[:-bytes_faltantes])


def test_u1b_detecta_respuesta_que_no_es_imagen():
    assert validar_imagen_descargada(NO_IMAGEN) == "no es una imagen"
    assert validar_imagen_descargada(b"") == "respuesta vacía"


def test_u1b_detecta_content_length_distinto():
    assert "tamaño" in validar_imagen_descargada(GIF_OK, str(len(GIF_OK) + 100))
    assert validar_imagen_descargada(GIF_OK, str(len(GIF_OK))) is None


# ── ingestar_url con reintentos ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_u1b_reintenta_y_recupera():
    """Primero llega cortado, después no es imagen, la tercera llega bien."""
    cliente = _cliente(_respuesta(GIF_CORTADO), _respuesta(NO_IMAGEN), _respuesta(GIF_OK))
    with (
        patch.object(ingestor.httpx, "AsyncClient", return_value=cliente),
        patch.object(ingestor.asyncio, "sleep", AsyncMock()) as dormir,
    ):
        resultado = await ingestar_url("https://dacc.test/latest.gif")

    assert resultado.raw_bytes == GIF_OK
    assert resultado.intentos_descarga == 3
    assert cliente.get.await_count == 3
    assert dormir.await_count == 2          # espera entre intentos, no después del último


@pytest.mark.asyncio
async def test_u1b_sin_reintento_si_llega_bien():
    cliente = _cliente(_respuesta(GIF_OK))
    with (
        patch.object(ingestor.httpx, "AsyncClient", return_value=cliente),
        patch.object(ingestor.asyncio, "sleep", AsyncMock()) as dormir,
    ):
        resultado = await ingestar_url("https://dacc.test/latest.gif")
    assert resultado.intentos_descarga == 1
    dormir.assert_not_awaited()


@pytest.mark.asyncio
async def test_u1b_se_rinde_y_entrega_lo_ultimo_recibido():
    cortados = [_respuesta(GIF_CORTADO) for _ in range(ingestor.DESCARGA_INTENTOS)]
    cliente = _cliente(*cortados)
    with (
        patch.object(ingestor.httpx, "AsyncClient", return_value=cliente),
        patch.object(ingestor.asyncio, "sleep", AsyncMock()),
    ):
        with pytest.raises(DescargaIncompletaError) as err:
            await ingestar_url("https://dacc.test/latest.gif")

    assert err.value.raw_bytes == GIF_CORTADO           # para guardarlo en la auditoría
    assert f"tras {ingestor.DESCARGA_INTENTOS} intentos" in str(err.value)
    assert cliente.get.await_count == ingestor.DESCARGA_INTENTOS


@pytest.mark.asyncio
async def test_u1b_respeta_content_length_del_servidor():
    """El servidor dice 10 bytes más de los que llegaron → incompleto, reintenta."""
    cliente = _cliente(
        _respuesta(GIF_OK, {"content-length": str(len(GIF_OK) + 10)}),
        _respuesta(GIF_OK, {"content-length": str(len(GIF_OK))}),
    )
    with (
        patch.object(ingestor.httpx, "AsyncClient", return_value=cliente),
        patch.object(ingestor.asyncio, "sleep", AsyncMock()),
    ):
        resultado = await ingestar_url("https://dacc.test/latest.gif")
    assert resultado.intentos_descarga == 2
