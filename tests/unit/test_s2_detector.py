"""
Tests del detector de celdas (Subsistema 2, F2) con campos sintéticos.

Los valores esperados se calculan a mano: discos y bloques de dBZ conocido
sobre una grilla de 650 m en EPSG:5344 (0,4225 km² por píxel).

    uv run pytest tests/unit/test_s2_detector.py -v
"""
from __future__ import annotations

import math
import re
from datetime import datetime

import numpy as np
import pytest

from src.subsistema2.detector import ParametrosDeteccion, detectar
from src.subsistema2.raster import Grilla, RasterDBZ

RES = 650.0
AREA_PX = 0.4225
GRILLA = Grilla(srid=5344, xmin=2_500_000.0, ymax=6_200_000.0, resolucion_m=RES, ancho=120, alto=100)
SIN_MINIMO = ParametrosDeteccion(area_min_km2=0)


def _raster(datos: np.ndarray, grilla: Grilla = GRILLA) -> RasterDBZ:
    return RasterDBZ(datos=datos.astype(np.uint8), transform=grilla.transform, crs=grilla.crs)


def _vacio() -> np.ndarray:
    return np.zeros(GRILLA.shape, np.uint8)


def _disco(arr: np.ndarray, fila: float, col: float, radio: float, dbz: int) -> np.ndarray:
    ff, cc = np.indices(arr.shape)
    sel = (ff - fila) ** 2 + (cc - col) ** 2 <= radio**2
    arr[sel] = dbz
    return sel


def _centro_px(fila: float, col: float) -> tuple[float, float]:
    """Coordenadas (x, y) del centro del píxel (fila, col) de la grilla de test."""
    return GRILLA.xmin + (col + 0.5) * RES, GRILLA.ymax - (fila + 0.5) * RES


def _area_wkt_km2(wkt: str) -> float:
    """Área de un MULTIPOLYGON WKT con la fórmula del trapecio (anillo 0 = exterior)."""
    total = 0.0
    for poly in re.findall(r"\(\((.*?)\)\)", wkt.replace(")), ((", "))|((")):
        for i, ring in enumerate(poly.split("), (")):
            pts = np.array([[float(v) for v in p.split()] for p in ring.strip("()").split(",")])
            a = 0.5 * abs(np.dot(pts[:-1, 0], pts[1:, 1]) - np.dot(pts[1:, 0], pts[:-1, 1]))
            total += a if i == 0 else -a
    return total / 1e6


# ── Atributos básicos ────────────────────────────────────────────────────────

def test_disco_uniforme_area_centroide_y_dbz():
    arr = _vacio()
    sel = _disco(arr, 50, 60, 6, 50)
    res = detectar(_raster(arr))

    assert len(res.celdas) == 1
    c = res.celdas[0]
    assert c.n_pixeles == int(sel.sum())
    assert c.area_km2 == pytest.approx(sel.sum() * AREA_PX)
    x, y = _centro_px(50, 60)
    assert (c.x_m, c.y_m) == (pytest.approx(x), pytest.approx(y))
    assert (c.x_geom_m, c.y_geom_m) == (pytest.approx(x), pytest.approx(y))
    assert c.dbz_max == 50
    assert c.dbz_medio == pytest.approx(50.0)
    assert c.dbz_medio <= c.dbz_max  # CHECK ck_celdas_dbz de la base
    assert c.elongacion == pytest.approx(1.0, abs=0.02)


def test_poligono_tiene_el_area_de_los_pixeles():
    arr = _vacio()
    _disco(arr, 40, 40, 8, 45)
    c = detectar(_raster(arr)).celdas[0]
    assert c.poligono_wkt.startswith("MULTIPOLYGON(((")
    assert _area_wkt_km2(c.poligono_wkt) == pytest.approx(c.area_km2)


def test_bbox_en_metros():
    arr = _vacio()
    arr[10:14, 20:25] = 40  # 4 filas × 5 columnas
    c = detectar(_raster(arr)).celdas[0]
    xmin, ymin, xmax, ymax = c.bbox
    assert xmin == pytest.approx(GRILLA.xmin + 20 * RES)
    assert xmax == pytest.approx(GRILLA.xmin + 25 * RES)
    assert ymax == pytest.approx(GRILLA.ymax - 10 * RES)
    assert ymin == pytest.approx(GRILLA.ymax - 14 * RES)


def test_ejemplo_del_manual_centroide_ponderado_y_dbz_medio():
    """Manual cap. 5: píxeles en x = 0, 1, 2 con 35, 45 y 55 dBZ."""
    arr = _vacio()
    arr[30, 10:13] = [35, 45, 55]
    c = detectar(_raster(arr), SIN_MINIMO).celdas[0]
    x0, _ = _centro_px(30, 10)
    assert (c.x_m - x0) / RES == pytest.approx(1.89, abs=0.005)   # sigue al núcleo
    assert (c.x_geom_m - x0) / RES == pytest.approx(1.0)
    assert c.dbz_medio == pytest.approx(50.7, abs=0.05)           # no 45
    assert c.dbz_max == 55


# ── Umbral, conectividad y área mínima ───────────────────────────────────────

def test_pixeles_bajo_umbral_y_sin_dato_no_forman_celdas():
    arr = _vacio()
    arr[10:30, 10:30] = 30   # lluvia moderada (< D1)
    arr[50:60, 50:60] = 10
    res = detectar(_raster(arr))
    assert res.celdas == []
    assert res.etiquetas.max() == 0


def test_imagen_vacia():
    res = detectar(_raster(_vacio()))
    assert res.celdas == [] and res.n_descartadas == 0


@pytest.mark.parametrize("conectividad, esperadas", [(8, 1), (4, 2)])
def test_conectividad_bloques_que_se_tocan_en_diagonal(conectividad, esperadas):
    arr = _vacio()
    arr[10:14, 10:14] = 45
    arr[14:18, 14:18] = 45
    res = detectar(_raster(arr), ParametrosDeteccion(area_min_km2=0, conectividad=conectividad))
    assert len(res.celdas) == esperadas


def test_celda_diagonal_es_un_multipoligono_de_dos_partes():
    arr = _vacio()
    arr[10:14, 10:14] = 45
    arr[14:18, 14:18] = 45
    c = detectar(_raster(arr), SIN_MINIMO).celdas[0]
    assert c.poligono_wkt.count("((") == 2
    assert _area_wkt_km2(c.poligono_wkt) == pytest.approx(32 * AREA_PX)


def test_area_minima_d3():
    """4 km² con píxeles de 0,4225 km²: 9 píxeles (3,80) no alcanzan, 10 (4,225) sí."""
    arr = _vacio()
    arr[5, 5:14] = 40     # 9 píxeles
    arr[20, 5:15] = 40    # 10 píxeles
    res = detectar(_raster(arr))
    assert [c.n_pixeles for c in res.celdas] == [10]
    assert res.n_descartadas == 1
    assert res.celdas[0].area_km2 == pytest.approx(4.225)


def test_etiquetas_consecutivas_y_coherentes_con_las_celdas():
    arr = _vacio()
    _disco(arr, 20, 20, 3, 40)
    arr[50, 50:53] = 40          # se descarta (3 px)
    _disco(arr, 70, 90, 5, 55)
    res = detectar(_raster(arr))
    assert [c.numero for c in res.celdas] == [1, 2]
    assert set(np.unique(res.etiquetas)) == {0, 1, 2}
    for c in res.celdas:
        assert int((res.etiquetas == c.numero).sum()) == c.n_pixeles


# ── Núcleos (D2) ─────────────────────────────────────────────────────────────

def test_nucleos_dentro_de_una_celda():
    arr = _vacio()
    arr[20:60, 20:80] = 38                      # sistema de 38 dBZ
    n1 = _disco(arr, 40, 35, 4, 55)             # dos núcleos separados
    n2 = _disco(arr, 40, 65, 3, 48)
    c = detectar(_raster(arr)).celdas[0]
    assert c.n_nucleos == 2
    assert c.area_nucleo_km2 == pytest.approx((n1.sum() + n2.sum()) * AREA_PX)
    assert c.dbz_max == 55
    assert c.area_nucleo_km2 <= c.area_km2


def test_celda_sin_nucleo():
    arr = _vacio()
    _disco(arr, 50, 50, 5, 40)
    c = detectar(_raster(arr)).celdas[0]
    assert c.n_nucleos == 0 and c.area_nucleo_km2 == 0


# ── Huecos y forma ───────────────────────────────────────────────────────────

def test_anillo_genera_poligono_con_hueco():
    arr = _vacio()
    arr[20:40, 20:40] = 45
    arr[25:35, 25:35] = 0
    c = detectar(_raster(arr)).celdas[0]
    assert c.n_pixeles == 400 - 100
    assert c.poligono_wkt.count("), (") == 1     # exterior + 1 interior
    assert _area_wkt_km2(c.poligono_wkt) == pytest.approx(300 * AREA_PX)


@pytest.mark.parametrize("azimut", [0, 45, 90, 135])
def test_orientacion_de_una_celda_alargada(azimut):
    """Elipse de semiejes 15 y 4 px con el eje mayor apuntando al azimut dado."""
    arr = _vacio()
    ff, cc = np.indices(arr.shape)
    dx, dy = cc - 60, -(ff - 50)                 # x al este, y al norte
    th = math.radians(azimut)
    u = dx * math.sin(th) + dy * math.cos(th)    # a lo largo del eje mayor
    v = dx * math.cos(th) - dy * math.sin(th)
    arr[(u / 15) ** 2 + (v / 4) ** 2 <= 1] = 45
    c = detectar(_raster(arr)).celdas[0]
    dif = abs((c.orientacion_deg - azimut + 90) % 180 - 90)
    assert dif < 3
    assert c.elongacion == pytest.approx(15 / 4, rel=0.1)


# ── Georreferencia y validaciones ────────────────────────────────────────────

def test_lon_lat_del_centroide():
    """El centroide en 5344 y su lon/lat tienen que ser el mismo punto."""
    from rasterio.warp import transform

    arr = _vacio()
    _disco(arr, 50, 60, 5, 50)
    c = detectar(_raster(arr)).celdas[0]
    xs, ys = transform("EPSG:4326", "EPSG:5344", [c.lon], [c.lat])
    assert xs[0] == pytest.approx(c.x_m, abs=0.01)
    assert ys[0] == pytest.approx(c.y_m, abs=0.01)
    assert -75 < c.lon < -60 and -40 < c.lat < -28


def test_rechaza_raster_en_3857():
    from rasterio.crs import CRS

    r = RasterDBZ(datos=_vacio(), transform=GRILLA.transform, crs=CRS.from_epsg(3857))
    with pytest.raises(ValueError, match="3857"):
        detectar(r)


def test_rechaza_raster_geografico():
    from rasterio.crs import CRS

    r = RasterDBZ(datos=_vacio(), transform=GRILLA.transform, crs=CRS.from_epsg(4326))
    with pytest.raises(ValueError, match="proyectado"):
        detectar(r)


@pytest.mark.parametrize("kwargs", [
    {"conectividad": 6}, {"umbral_dbz": 45, "umbral_nucleo_dbz": 35}, {"area_min_km2": -1},
])
def test_parametros_invalidos(kwargs):
    with pytest.raises(ValueError):
        ParametrosDeteccion(**kwargs)


def test_parametros_desde_settings_y_como_dict():
    p = ParametrosDeteccion.desde_settings()
    assert p.como_dict() == {"umbral_dbz": 35.0, "umbral_nucleo_dbz": 45.0,
                             "area_min_km2": 4.0, "conectividad": 8}


def test_celda_se_convierte_a_fila_del_repositorio():
    arr = _vacio()
    _disco(arr, 50, 60, 5, 50)
    c = detectar(_raster(arr)).celdas[0]
    fila = c.a_celda_nueva(imagen_id=7, fecha_hora=datetime(2025, 1, 6, 15, 0), geo_corregida=True)
    assert fila.imagen_id == 7 and fila.numero == c.numero
    assert (fila.x_m, fila.y_m) == (c.x_m, c.y_m)
    assert fila.area_km2 == c.area_km2 and fila.area_nucleo_km2 == c.area_nucleo_km2
    assert fila.poligono_wkt == c.poligono_wkt and fila.geo_corregida is True
