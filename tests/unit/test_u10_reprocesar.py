"""
U10 — reprocesar_imagen: vuelve a correr las fases 2-7 desde raw_data.

Los repositorios y las fases se sustituyen: se prueba la orquestación
(qué se borra, con qué se llama al pipeline), no el procesamiento.
"""
from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from src.subsistema1 import orquestador


def _gif() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 6), (0, 90, 0)).save(buf, format="GIF")
    return buf.getvalue()


@pytest.fixture
def registro(monkeypatch):
    eventos: list[tuple] = []
    imagenes = {1: SimpleNamespace(id=1, raw_data=_gif()), 2: SimpleNamespace(id=2, raw_data=None)}

    class ImgRepo:
        def __init__(self, _s): pass
        async def obtener_por_id(self, i): return imagenes.get(i)
        async def actualizar_estado(self, i, e): eventos.append(("estado", i, e))

    class MetricaRepo:
        def __init__(self, _s): pass
        async def eliminar_por_imagen(self, i): eventos.append(("borrar_metricas", i))

    class PasoRepo:
        def __init__(self, _s): pass

    async def fases(**kw):
        eventos.append(("fases", kw["imagen_id"], kw["pil_image"].size, kw["raw_bytes"]))
        return orquestador.ResultadoPipeline(kw["imagen_id"], orquestador.MetricasPipeline(), True)

    monkeypatch.setattr(orquestador, "ImagenRadarRepository", ImgRepo)
    monkeypatch.setattr(orquestador, "MetricaProcesamientoRepository", MetricaRepo)
    monkeypatch.setattr(orquestador, "ProcesamentoPasoRepository", PasoRepo)
    monkeypatch.setattr(orquestador, "_ejecutar_fases_comunes", fases)
    return eventos, imagenes


def test_u10_reprocesa_desde_raw_y_reemplaza_metricas(registro):
    eventos, imagenes = registro
    resultado = asyncio.run(orquestador.reprocesar_imagen(1, session=None))
    assert resultado.exito
    assert eventos == [
        ("borrar_metricas", 1),
        ("estado", 1, "procesando"),
        ("fases", 1, (8, 6), imagenes[1].raw_data),
    ]


@pytest.mark.parametrize("imagen_id", [2, 99])
def test_u10_sin_raw_o_inexistente_no_toca_nada(registro, imagen_id):
    eventos, _ = registro
    with pytest.raises(ValueError):
        asyncio.run(orquestador.reprocesar_imagen(imagen_id, session=None))
    assert eventos == []
