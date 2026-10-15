"""
U8 — Auditoría de descargas (radar.intentos_descarga).

Cada intento de descarga desde la URL del DACC tiene que quedar registrado con
fecha y hora, positivo/negativo y motivo, AUNQUE el pipeline se descarte y su
sesión haga rollback. Antes del 15/10/2026 los negativos se perdían.

Se usa una base SQLite real (en memoria) solo para la tabla de auditoría; el
resto del pipeline va mockeado.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.db.models import IntentoDescarga
from src.subsistema1 import orquestador
from src.subsistema1.ingestor import DescargaIncompletaError
from src.subsistema1.orquestador import (
    DuplicadoError,
    ResultadoPipeline,
    MetricasPipeline,
    ejecutar_pipeline_url,
)

URL = "https://dacc.test/radar/latest.gif"
HORA_IMAGEN = datetime(2026, 10, 13, 4, 30)


# ── Base de auditoría de prueba ───────────────────────────────────────────────

@pytest_asyncio.fixture
async def auditoria(monkeypatch):
    """Factory de sesiones sobre SQLite con la tabla radar.intentos_descarga,
    inyectada como la sesión propia de la auditoría."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _schema_radar(dbapi_conn, _):
        dbapi_conn.execute("ATTACH DATABASE ':memory:' AS radar")

    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: IntentoDescarga.metadata.create_all(c, tables=[IntentoDescarga.__table__])
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(orquestador, "AsyncSessionLocal", factory)
    yield factory
    await engine.dispose()


async def _intentos(factory) -> list[IntentoDescarga]:
    async with factory() as s:
        res = await s.execute(select(IntentoDescarga).order_by(IntentoDescarga.id))
        return list(res.scalars())


# ── Mocks del pipeline ────────────────────────────────────────────────────────

def _ingesta():
    return SimpleNamespace(imagen_pil=MagicMock(), fecha_hora=None, raw_bytes=b"GIF89a-falso")


def _repo_imagenes(existente_hora=None, existente_hash=None):
    repo = MagicMock()
    repo.obtener_por_fecha_hora = AsyncMock(return_value=existente_hora)
    repo.obtener_por_hash = AsyncMock(return_value=existente_hash)
    repo.crear = AsyncMock(return_value=SimpleNamespace(id=999))
    repo.actualizar_estado = AsyncMock()
    return repo


def _sesion_pipeline():
    """La sesión del pipeline: si algo falla, el llamador hace rollback.
    Acá es un mock: nada de lo que se haga en ella llega a la base."""
    return MagicMock()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestAuditoriaDescargas:

    @pytest.mark.asyncio
    async def test_u8_duplicado_contenido_queda_registrado_como_negativo(self, auditoria):
        """El caso de la madrugada del 13/10: el DACC no actualizó el GIF."""
        existente = SimpleNamespace(id=700, fecha_hora=datetime(2026, 10, 13, 4, 28))
        with (
            patch.object(orquestador, "ingestar_url", AsyncMock(return_value=_ingesta())),
            patch.object(orquestador, "_resolver_timestamp", AsyncMock(return_value=HORA_IMAGEN)),
            patch.object(orquestador, "ImagenRadarRepository",
                         return_value=_repo_imagenes(existente_hash=existente)),
        ):
            with pytest.raises(DuplicadoError):
                await ejecutar_pipeline_url(_sesion_pipeline(), url=URL)

        filas = await _intentos(auditoria)
        assert len(filas) == 1
        assert filas[0].exitoso is False
        assert filas[0].motivo_fallo.startswith("duplicado_contenido:")
        assert filas[0].fecha_intento is not None

    @pytest.mark.asyncio
    async def test_u8_duplicado_hora(self, auditoria):
        existente = SimpleNamespace(id=700, fecha_hora=HORA_IMAGEN)
        with (
            patch.object(orquestador, "ingestar_url", AsyncMock(return_value=_ingesta())),
            patch.object(orquestador, "_resolver_timestamp", AsyncMock(return_value=HORA_IMAGEN)),
            patch.object(orquestador, "ImagenRadarRepository",
                         return_value=_repo_imagenes(existente_hora=existente)),
        ):
            with pytest.raises(ValueError):  # el scheduler lo sigue viendo como ValueError
                await ejecutar_pipeline_url(_sesion_pipeline(), url=URL)

        filas = await _intentos(auditoria)
        assert [f.exitoso for f in filas] == [False]
        assert filas[0].motivo_fallo.startswith("duplicado_hora:")

    @pytest.mark.asyncio
    async def test_u8_falla_de_descarga(self, auditoria):
        with patch.object(orquestador, "ingestar_url",
                          AsyncMock(side_effect=ConnectionError("timeout DACC"))):
            with pytest.raises(ConnectionError):
                await ejecutar_pipeline_url(_sesion_pipeline(), url=URL)

        filas = await _intentos(auditoria)
        assert filas[0].exitoso is False
        assert filas[0].motivo_fallo.startswith("descarga:")
        assert "timeout DACC" in filas[0].motivo_fallo

    @pytest.mark.asyncio
    async def test_u8_falla_ocr(self, auditoria):
        with (
            patch.object(orquestador, "ingestar_url", AsyncMock(return_value=_ingesta())),
            patch.object(orquestador, "_resolver_timestamp",
                         AsyncMock(side_effect=ValueError("No se pudo determinar fecha/hora"))),
        ):
            with pytest.raises(ValueError):
                await ejecutar_pipeline_url(_sesion_pipeline(), url=URL)

        filas = await _intentos(auditoria)
        assert filas[0].motivo_fallo.startswith("ocr:")

    @pytest.mark.asyncio
    async def test_u8_exito_queda_registrado_como_positivo(self, auditoria):
        ok = ResultadoPipeline(imagen_id=999, metricas=MetricasPipeline(), exito=True)
        with (
            patch.object(orquestador, "ingestar_url", AsyncMock(return_value=_ingesta())),
            patch.object(orquestador, "_resolver_timestamp", AsyncMock(return_value=HORA_IMAGEN)),
            patch.object(orquestador, "ImagenRadarRepository", return_value=_repo_imagenes()),
            patch.object(orquestador, "_ejecutar_fases_comunes", AsyncMock(return_value=ok)),
        ):
            resultado = await ejecutar_pipeline_url(_sesion_pipeline(), url=URL)

        assert resultado.exito
        filas = await _intentos(auditoria)
        assert len(filas) == 1
        assert filas[0].exitoso is True
        assert filas[0].motivo_fallo is None

    @pytest.mark.asyncio
    async def test_u8_pipeline_fallido_es_negativo(self, auditoria):
        mal = ResultadoPipeline(imagen_id=999, metricas=MetricasPipeline(), exito=False,
                                mensaje_error="fallo en geolocalizar")
        with (
            patch.object(orquestador, "ingestar_url", AsyncMock(return_value=_ingesta())),
            patch.object(orquestador, "_resolver_timestamp", AsyncMock(return_value=HORA_IMAGEN)),
            patch.object(orquestador, "ImagenRadarRepository", return_value=_repo_imagenes()),
            patch.object(orquestador, "_ejecutar_fases_comunes", AsyncMock(return_value=mal)),
        ):
            await ejecutar_pipeline_url(_sesion_pipeline(), url=URL)

        filas = await _intentos(auditoria)
        assert filas[0].exitoso is False
        assert filas[0].motivo_fallo == "pipeline: fallo en geolocalizar"

    @pytest.mark.asyncio
    async def test_u8_un_intento_por_ciclo_y_numeracion(self, auditoria):
        """Tres ciclos seguidos = tres filas, con intento_numero 1, 2, 3."""
        for _ in range(3):
            with patch.object(orquestador, "ingestar_url",
                              AsyncMock(side_effect=ConnectionError("x"))):
                with pytest.raises(ConnectionError):
                    await ejecutar_pipeline_url(_sesion_pipeline(), url=URL)
        filas = await _intentos(auditoria)
        assert [f.intento_numero for f in filas] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_u8_motivo_largo_se_recorta_a_100(self, auditoria):
        with patch.object(orquestador, "ingestar_url",
                          AsyncMock(side_effect=ConnectionError("x" * 500))):
            with pytest.raises(ConnectionError):
                await ejecutar_pipeline_url(_sesion_pipeline(), url=URL)
        filas = await _intentos(auditoria)
        assert len(filas[0].motivo_fallo) == 100

    @pytest.mark.asyncio
    async def test_u8_si_la_auditoria_falla_no_rompe_el_pipeline(self):
        def factory_rota():
            raise RuntimeError("base de auditoría caída")

        # No tiene que lanzar: solo loguea.
        await orquestador._registrar_intento(URL, True, None, datetime(2026, 10, 15),
                                             session_factory=factory_rota)


class TestArchivoRechazado:
    """Desde el 15/10/2026 se guardan los bytes de los intentos rechazados por
    GIF incompleto u OCR, para poder mirarlos (columna archivo)."""

    @pytest.mark.asyncio
    async def test_u8_gif_incompleto_guarda_archivo(self, auditoria):
        with patch.object(orquestador, "ingestar_url", AsyncMock(
                side_effect=DescargaIncompletaError("GIF incompleto tras 3 intentos: x", b"GIF89a-cortado"))):
            with pytest.raises(DescargaIncompletaError):
                await ejecutar_pipeline_url(_sesion_pipeline(), url=URL)
        fila = (await _intentos(auditoria))[0]
        assert fila.exitoso is False
        assert fila.motivo_fallo.startswith("descarga: GIF incompleto")
        assert fila.archivo == b"GIF89a-cortado"

    @pytest.mark.asyncio
    async def test_u8_fallo_ocr_guarda_archivo(self, auditoria):
        with (
            patch.object(orquestador, "ingestar_url", AsyncMock(return_value=_ingesta())),
            patch.object(orquestador, "_resolver_timestamp",
                         AsyncMock(side_effect=ValueError("sin marco legible"))),
        ):
            with pytest.raises(ValueError):
                await ejecutar_pipeline_url(_sesion_pipeline(), url=URL)
        fila = (await _intentos(auditoria))[0]
        assert fila.motivo_fallo.startswith("ocr:")
        assert fila.archivo == b"GIF89a-falso"

    @pytest.mark.asyncio
    async def test_u8_duplicado_no_guarda_archivo(self, auditoria):
        """El contenido de un duplicado ya está en la base: no se repite."""
        existente = SimpleNamespace(id=700, fecha_hora=HORA_IMAGEN)
        with (
            patch.object(orquestador, "ingestar_url", AsyncMock(return_value=_ingesta())),
            patch.object(orquestador, "_resolver_timestamp", AsyncMock(return_value=HORA_IMAGEN)),
            patch.object(orquestador, "ImagenRadarRepository",
                         return_value=_repo_imagenes(existente_hora=existente)),
        ):
            with pytest.raises(DuplicadoError):
                await ejecutar_pipeline_url(_sesion_pipeline(), url=URL)
        assert (await _intentos(auditoria))[0].archivo is None

    @pytest.mark.asyncio
    async def test_u8_positivo_no_guarda_archivo(self, auditoria):
        ok = ResultadoPipeline(imagen_id=999, metricas=MetricasPipeline(), exito=True)
        with (
            patch.object(orquestador, "ingestar_url", AsyncMock(return_value=_ingesta())),
            patch.object(orquestador, "_resolver_timestamp", AsyncMock(return_value=HORA_IMAGEN)),
            patch.object(orquestador, "ImagenRadarRepository", return_value=_repo_imagenes()),
            patch.object(orquestador, "_ejecutar_fases_comunes", AsyncMock(return_value=ok)),
        ):
            await ejecutar_pipeline_url(_sesion_pipeline(), url=URL)
        assert (await _intentos(auditoria))[0].archivo is None
