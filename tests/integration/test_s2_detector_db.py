"""
Del detector (F2) a PostGIS: las celdas detectadas entran en
radar.celdas_tormenta sin violar ninguna restricción y la base mide lo mismo
que el detector (área del polígono, lon/lat del centroide).

Misma base de test que test_tracking_repo.py (radar_test, nunca radar_db).
Si no hay Postgres, se saltean.

    docker compose up db -d
    uv run pytest tests/integration/test_s2_detector_db.py -v
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest
from sqlalchemy import text

from src.subsistema2.detector import detectar
from src.subsistema2.raster import Grilla, RasterDBZ
from tests.integration.test_tracking_repo import _ejecucion, _imagenes, base_postgis, s  # noqa: F401

T0 = datetime(2025, 1, 6, 15, 12)


def _campo() -> RasterDBZ:
    """Celdas con forma difícil: disco, anillo con hueco, dos bloques en diagonal y una línea."""
    g = Grilla.desde_settings()
    arr = np.zeros(g.shape, np.uint8)
    ff, cc = np.indices(g.shape)
    arr[(ff - 400) ** 2 + (cc - 400) ** 2 <= 64] = 55
    arr[300:320, 500:520] = 45
    arr[305:315, 505:515] = 0
    arr[200:204, 200:204] = 40
    arr[204:208, 204:208] = 48
    arr[600, 300:330] = 36
    return RasterDBZ(datos=arr, transform=g.transform, crs=g.crs)


@pytest.mark.asyncio
async def test_celdas_detectadas_se_guardan_y_la_base_mide_lo_mismo(s):  # noqa: F811
    from src.db.repository_tracking import CeldaTormentaRepository

    res = detectar(_campo())
    assert len(res.celdas) == 4
    ej = await _ejecucion(s)
    (img,) = await _imagenes(s, 1)
    filas = [c.a_celda_nueva(img, T0) for c in res.celdas]
    ids = await CeldaTormentaRepository(s).crear_varias(ej.id, filas)
    assert len(ids) == 4

    q = await s.execute(text("""
        SELECT numero, ST_IsValid(poligono), ST_Area(poligono) / 1e6, lon, lat,
               ST_NumGeometries(poligono), ST_NumInteriorRings(ST_GeometryN(poligono, 1))
        FROM radar.celdas_tormenta WHERE ejecucion_id = :e ORDER BY numero"""), {"e": ej.id})
    por_numero = {c.numero: c for c in res.celdas}
    for numero, valido, area_db, lon, lat, n_partes, n_huecos in q.all():
        c = por_numero[numero]
        assert valido, f"polígono inválido en la celda {numero}"
        assert area_db == pytest.approx(c.area_km2, rel=1e-6)
        assert lon == pytest.approx(c.lon, abs=1e-7) and lat == pytest.approx(c.lat, abs=1e-7)
        if c.n_pixeles == 32:          # bloques en diagonal → 2 partes
            assert n_partes == 2
        if c.n_pixeles == 300:         # anillo → 1 hueco
            assert n_huecos == 1
