"""
Tests de lectura y reproyección del GeoTIFF (Subsistema 2, F2).

Se arma un GeoTIFF en EPSG:3857 igual al que guarda el Subsistema 1
(uint8, nodata 0, píxel nominal de 790,256 m) y se verifica que, llevado a
la grilla 5344, las áreas y posiciones son las reales del terreno.

    uv run pytest tests/unit/test_s2_raster.py -v
"""
from __future__ import annotations

import io
import math

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.warp import transform

from src.subsistema2.detector import ParametrosDeteccion, detectar
from src.subsistema2.raster import Grilla, cargar_en_grilla, leer_geotiff, reproyectar

PX_3857 = 790.256
# Esquina NO cerca de San Rafael (mismo orden que los GeoTIFF reales)
T_3857 = Affine(PX_3857, 0.0, -7_640_000.0, 0.0, -PX_3857, -4_080_000.0)


def _geotiff_3857(datos: np.ndarray, t: Affine = T_3857, nodata: int | None = 0) -> bytes:
    buf = io.BytesIO()
    with rasterio.open(buf, "w", driver="GTiff", height=datos.shape[0], width=datos.shape[1],
                       count=1, dtype="uint8", crs="EPSG:3857", transform=t, nodata=nodata) as dst:
        dst.write(datos.astype(np.uint8), 1)
    return buf.getvalue()


@pytest.fixture(scope="module")
def grilla() -> Grilla:
    return Grilla.desde_settings()


def test_grilla_por_defecto(grilla):
    assert grilla.srid == 5344 and grilla.resolucion_m == 650
    assert grilla.area_pixel_km2 == pytest.approx(0.4225)
    xmin, ymin, xmax, ymax = grilla.limites
    # cubre el marco más grande del radar (template tif800: lon −70,69° a −65,11°,
    # lat −36,66° a −31,27°); en 5344 los meridianos convergen, por eso las 4 esquinas
    xs, ys = transform("EPSG:4326", "EPSG:5344", [-70.69, -65.11, -70.69, -65.11],
                       [-36.66, -36.66, -31.27, -31.27])
    assert xmin < min(xs) and xmax > max(xs) and ymin < min(ys) and ymax > max(ys)


def test_leer_geotiff_respeta_datos_y_georreferencia():
    datos = np.zeros((50, 60), np.uint8)
    datos[10:20, 10:20] = 45
    r = leer_geotiff(_geotiff_3857(datos))
    assert r.crs.to_epsg() == 3857
    assert r.transform == T_3857
    assert np.array_equal(r.datos, datos)


def test_leer_geotiff_vacio_falla():
    with pytest.raises(ValueError):
        leer_geotiff(b"")


def test_nodata_distinto_de_cero_se_lleva_a_cero():
    datos = np.full((20, 20), 255, np.uint8)
    datos[5:10, 5:10] = 40
    r = leer_geotiff(_geotiff_3857(datos, nodata=255))
    assert set(np.unique(r.datos)) == {0, 40}


def test_reproyeccion_conserva_categorias_y_forma(grilla):
    datos = np.zeros((300, 300), np.uint8)
    datos[100:140, 100:140] = 45
    datos[110:120, 110:120] = 60
    datos[200:220, 50:80] = 36
    r = cargar_en_grilla(_geotiff_3857(datos), grilla)
    assert r.shape == grilla.shape and r.datos.dtype == np.uint8
    assert r.crs.to_epsg() == 5344 and r.transform == grilla.transform
    # vecino más cercano: no aparecen valores intermedios
    assert set(np.unique(r.datos)) <= {0, 36, 45, 60}


def test_area_real_y_no_la_de_web_mercator(grilla):
    """
    Un bloque de 40×40 píxeles de 3857 mide 31,6 km de lado "nominal", pero en
    el terreno a −34,5° mide 31,6·cos(lat) ≈ 26 km. Después de reproyectar, el
    detector tiene que dar el área real (±3 %), no la nominal (~45 % más).
    """
    datos = np.zeros((300, 300), np.uint8)
    datos[100:140, 100:140] = 45
    celdas = detectar(cargar_en_grilla(_geotiff_3857(datos), grilla)).celdas
    assert len(celdas) == 1

    # área "verdadera": esquinas del bloque en lon/lat → 5344 (error de escala ≤ 0,16 %)
    esquinas = [T_3857 * (c, f) for c, f in ((100, 100), (140, 100), (140, 140), (100, 140))]
    xs, ys = transform("EPSG:3857", "EPSG:5344", *zip(*esquinas))
    real_km2 = 0.5 * abs(sum(xs[i] * ys[i - 1] - xs[i - 1] * ys[i] for i in range(4))) / 1e6
    nominal_km2 = (40 * PX_3857) ** 2 / 1e6

    assert celdas[0].area_km2 == pytest.approx(real_km2, rel=0.03)
    assert nominal_km2 / real_km2 > 1.4   # lo que se evitaría


def test_centroide_cae_donde_estaba_el_bloque(grilla):
    datos = np.zeros((300, 300), np.uint8)
    datos[100:140, 100:140] = 45
    c = detectar(cargar_en_grilla(_geotiff_3857(datos), grilla)).celdas[0]
    cx, cy = T_3857 * (120, 120)                     # centro del bloque en 3857
    xs, ys = transform("EPSG:3857", "EPSG:5344", [cx], [cy])
    assert math.hypot(c.x_m - xs[0], c.y_m - ys[0]) < grilla.resolucion_m


def test_transform_origen_desplaza_la_imagen(grilla):
    """Gancho de D13: con otro transform, la misma celda aparece corrida."""
    datos = np.zeros((300, 300), np.uint8)
    datos[100:140, 100:140] = 45
    b = _geotiff_3857(datos)
    base = detectar(cargar_en_grilla(b, grilla)).celdas[0]
    corrido = T_3857 * Affine.translation(0, -4)    # 4 píxeles de 3857 hacia el norte
    mov = detectar(cargar_en_grilla(b, grilla, transform_origen=corrido)).celdas[0]
    dy = mov.y_m - base.y_m
    assert dy > 0                                   # se movió al norte
    assert dy == pytest.approx(4 * PX_3857 * math.cos(math.radians(34.5)), rel=0.2)
    assert abs(mov.x_m - base.x_m) < grilla.resolucion_m


def test_imagen_fuera_de_la_grilla_queda_vacia(grilla):
    lejos = Affine(PX_3857, 0.0, -9_000_000.0, 0.0, -PX_3857, -2_000_000.0)
    datos = np.full((50, 50), 45, np.uint8)
    r = reproyectar(leer_geotiff(_geotiff_3857(datos, t=lejos)), grilla)
    assert r.datos.max() == 0
    assert detectar(r, ParametrosDeteccion()).celdas == []
