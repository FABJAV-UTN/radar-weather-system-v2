"""
U9 — API del carrusel y descarga por lote con fecha y hora.

El router se monta en una app mínima, con la sesión y el usuario sustituidos
y el repositorio reemplazado por uno en memoria: se prueba el contrato HTTP,
no la base de datos.
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from rasterio.crs import CRS
from rasterio.transform import Affine

from src.api.dependencies import get_current_user, get_db
from src.api.routers import imagenes
from src.api.vista_dbz import geotiff_a_vista
from src.subsistema1.geolocalizar import dbz_array_to_geotiff_bytes

NIVELES = (0, 10, 20, 30, 35, 45, 65, 80)


def _geotiff(dbz: np.ndarray) -> bytes:
    return dbz_array_to_geotiff_bytes(
        dbz, Affine(870.0, 0, -7_900_000.0, 0, -870.0, -3_800_000.0), CRS.from_epsg(3857)
    )


def _dbz_ejemplo() -> np.ndarray:
    rng = np.random.default_rng(0)
    return np.array(NIVELES, np.uint8)[rng.integers(0, len(NIVELES), (40, 30))]


class RepoFalso:
    """Reemplaza a ImagenRadarRepository con datos en memoria."""

    serie: list[tuple[int, datetime]] = []
    geotiffs: list[tuple[int, datetime, bytes]] = []
    llamadas: list[tuple] = []

    def __init__(self, _session) -> None:
        pass

    async def listar_serie(self, desde, hasta, limite):
        RepoFalso.llamadas.append(("serie", desde, hasta, limite))
        return RepoFalso.serie[:limite]

    async def listar_geotiffs_por_rango(self, desde, hasta):
        RepoFalso.llamadas.append(("lote", desde, hasta))
        return RepoFalso.geotiffs

    async def obtener_geotiff(self, imagen_id):
        return next((g for i, _, g in RepoFalso.geotiffs if i == imagen_id), None)


@pytest.fixture
def cliente(monkeypatch):
    RepoFalso.serie, RepoFalso.geotiffs, RepoFalso.llamadas = [], [], []
    monkeypatch.setattr(imagenes, "ImagenRadarRepository", RepoFalso)
    app = FastAPI()
    app.include_router(imagenes.router)
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {"sub": 1, "role": "visualizador"}
    return TestClient(app)


# ── Vista PNG ─────────────────────────────────────────────────────────────────

def test_u9_vista_png_conserva_valor_dbz_de_cada_pixel():
    dbz = _dbz_ejemplo()
    png = Image.open(io.BytesIO(geotiff_a_vista(_geotiff(dbz)).png))
    assert png.mode == "L"
    np.testing.assert_array_equal(np.array(png), dbz)


def test_u9_vista_informa_limites_en_grados():
    """Los límites del cuadro (EPSG:3857) se devuelven en lon/lat: oeste, sur, este, norte."""
    oeste, sur, este, norte = geotiff_a_vista(_geotiff(_dbz_ejemplo())).limites
    # transform de _geotiff: origen (-7.900.000; -3.800.000) m, píxel 870 m, 30 × 40 px.
    # Esperados con las fórmulas de Mercator esférico (R = 6.378.137 m).
    assert oeste == pytest.approx(-70.96691, abs=1e-4)
    assert este == pytest.approx(-70.73245, abs=1e-4)
    assert norte == pytest.approx(-32.27908, abs=1e-4)
    assert sur == pytest.approx(-32.54299, abs=1e-4)
    assert oeste < este and sur < norte


def test_u9_endpoint_vista_devuelve_png(cliente):
    dbz = _dbz_ejemplo()
    RepoFalso.geotiffs = [(7, datetime(2026, 10, 13, 11, 2), _geotiff(dbz))]
    r = cliente.get("/imagenes/7/vista")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert len(r.headers["x-limites"].split(",")) == 4
    np.testing.assert_array_equal(np.array(Image.open(io.BytesIO(r.content))), dbz)


def test_u9_endpoint_vista_sin_geotiff_404(cliente):
    assert cliente.get("/imagenes/99/vista").status_code == 404


# ── Serie del carrusel ────────────────────────────────────────────────────────

def test_u9_serie_respeta_hora_y_orden(cliente):
    RepoFalso.serie = [(1, datetime(2026, 10, 13, 10, 10)), (2, datetime(2026, 10, 13, 10, 12))]
    r = cliente.get("/imagenes/serie", params={"desde": "2026-10-13T10:00", "hasta": "2026-10-13T11:50"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert [f["id"] for f in cuerpo["items"]] == [1, 2]
    assert cuerpo["truncada"] is False
    _, desde, hasta, _ = RepoFalso.llamadas[0]
    assert (desde, hasta) == (datetime(2026, 10, 13, 10, 0), datetime(2026, 10, 13, 11, 50))


def test_u9_serie_marca_truncada(cliente, monkeypatch):
    monkeypatch.setattr(imagenes, "MAX_FRAMES_SERIE", 2)
    RepoFalso.serie = [(i, datetime(2026, 10, 13, 10, i)) for i in range(5)]
    cuerpo = cliente.get("/imagenes/serie", params={"desde": "2026-10-13T00:00",
                                                    "hasta": "2026-10-13T23:59"}).json()
    assert len(cuerpo["items"]) == 2
    assert cuerpo["truncada"] is True


def test_u9_serie_rechaza_rango_invertido(cliente):
    r = cliente.get("/imagenes/serie", params={"desde": "2026-10-13T12:00", "hasta": "2026-10-13T10:00"})
    assert r.status_code == 422


# ── Descarga por lote ─────────────────────────────────────────────────────────

def test_u9_lote_con_hora_arma_zip_completo(cliente):
    tif = _geotiff(_dbz_ejemplo())
    RepoFalso.geotiffs = [
        (708, datetime(2026, 10, 13, 10, 10), tif),
        (709, datetime(2026, 10, 13, 10, 12), tif),
    ]
    r = cliente.get("/imagenes/descargar-lote",
                    params={"desde": "2026-10-13T10:00", "hasta": "2026-10-13T10:30"})
    assert r.status_code == 200
    assert 'filename="radar_20261013_1000_20261013_1030.zip"' in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.namelist() == ["radar_708_20261013_101000.tif", "radar_709_20261013_101200.tif"]
        assert zf.read("radar_708_20261013_101000.tif") == tif  # sin filtrar niveles
    _, desde, hasta = RepoFalso.llamadas[0]
    assert (desde, hasta) == (datetime(2026, 10, 13, 10, 0), datetime(2026, 10, 13, 10, 30))


def test_u9_lote_sin_imagenes_404(cliente):
    r = cliente.get("/imagenes/descargar-lote",
                    params={"desde": "2026-10-13T10:00", "hasta": "2026-10-13T10:30"})
    assert r.status_code == 404
