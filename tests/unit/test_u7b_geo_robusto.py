"""
U7b — Geolocalización robusta (src/subsistema1/geolocalizar.py, camino calibrado).

Cubre cada capa por separado con imágenes sintéticas, el desvío al legado para
tamaños sin calibrar, el calibrador de variantes y, opcionalmente, la regresión
con los 189 TIF reales de la noche del 13/10/2026:

    GEO_TIF_DIR="$HOME/OneDrive/UNCUYO/PROYECTO CLIMA/radar_2026-10-13_2026-10-13 (1)" \
        uv run pytest tests/unit/test_u7b_geo_robusto.py -v
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio

from src.subsistema1 import geolocalizar as geo

RAIZ = Path(__file__).resolve().parents[2]
DIR_TEMPLATES = RAIZ / "templates"
sys.path.insert(0, str(RAIZ / "scripts"))

VARIANTE = "dacc_scheduler_560x741"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def geometrias():
    return geo.cargar_geometrias(DIR_TEMPLATES / geo.NOMBRE_GEOMETRIAS)


@pytest.fixture(scope="module")
def g(geometrias):
    return geometrias[VARIANTE]


def _forma_irregular(alto: int, ancho: int, semilla: int) -> np.ndarray:
    """Forma rala e irregular, parecida a un eco de clutter."""
    rng = np.random.default_rng(semilla)
    forma = rng.random((alto, ancho)) > 0.6
    forma[:, : ancho // 3] &= rng.random((alto, ancho // 3)) > 0.3
    return forma


@pytest.fixture(scope="module")
def eco_sintetico(g):
    """Un único eco fijo (como en la realidad) y su esquina en la variante.

    Los dos templates son recortes distintos de ESTE eco, ubicados según
    g.ecos, igual que template_eco_fijo y template_eco_fijo2.
    """
    esquinas = list(g.ecos.values())
    col0 = min(c for c, _ in esquinas)
    row0 = min(r for _, r in esquinas)
    return _forma_irregular(90, 50, 7), (col0, row0)


@pytest.fixture(scope="module")
def templates_sinteticos(g, eco_sintetico):
    campo, (col0, row0) = eco_sintetico
    tps = []
    for nombre in geo.NOMBRES_TEMPLATES_ECO:
        col, row = g.ecos[nombre]
        forma = campo[row - row0: row - row0 + 70, col - col0: col - col0 + 40].copy()
        dbz = np.where(forma, 45, 0).astype(np.uint8)
        tps.append(geo.TemplateEco(nombre=nombre, dbz=dbz, umbral=35,
                                   mascara=geo.mascara_dbz(dbz, 35), forma=forma))
    return tps


def _imagen_con_ecos(g, eco, dc=0, dr=0, senuelo=False) -> np.ndarray:
    """dbz (741, 560) con el eco fijo en su posición nominal + (dc, dr)."""
    campo, (col0, row0) = eco
    dbz = np.zeros((g.alto, g.ancho), dtype=np.uint8)
    h, w = campo.shape
    dbz[row0 + dr: row0 + dr + h, col0 + dc: col0 + dc + w][campo] = 45
    if senuelo:
        # campo de lluvia ancho y continuo al sur-este (San Rafael / Nihuil)
        dbz[520:700, 250:450] = 20
        dbz[560:640, 300:400] = 40
    return dbz


# ── Capa 0: geometría ─────────────────────────────────────────────────────────

def test_cargar_geometrias_lee_variante_scheduler(g):
    assert (g.ancho, g.alto) == (560, 741)
    assert g.pixel_m == pytest.approx(722.54)
    assert set(g.ecos) == set(geo.NOMBRES_TEMPLATES_ECO)


def test_elegir_geometria_tamano_exacto(geometrias):
    assert geo.elegir_geometria((741, 560), geometrias).nombre == VARIANTE


def test_elegir_geometria_tamano_desconocido_devuelve_none(geometrias):
    assert geo.elegir_geometria((740, 560), geometrias) is None
    assert geo.elegir_geometria((842, 761), geometrias) is None


def test_cero_km_cae_en_el_pixel_del_eje(g):
    """El CENTRO del píxel del 0 km tiene que caer en x=0, y=0 (el radar)."""
    x, y = g.transform() * (g.c0 + 0.5, g.r0 + 0.5)
    assert x == pytest.approx(0.0, abs=1e-6)
    assert y == pytest.approx(0.0, abs=1e-6)


def test_transform_corrimiento_mueve_origen(g):
    """Ecos corridos (+3, −2) px → el mismo punto del terreno está 3 col a la derecha y 2 filas arriba."""
    t0, t1 = g.transform(), g.transform(3, -2)
    assert t1 * (g.c0 + 3, g.r0 - 2) == pytest.approx(t0 * (g.c0, g.r0))


def test_crs_es_aeqd_centrado_en_radar(g):
    p4 = g.crs.to_proj4()
    assert "+proj=aeqd" in p4 and "-33.4917" in p4 and "-69.0217" in p4


# ── Capa 1: máscaras dBZ ──────────────────────────────────────────────────────

def test_mascara_dbz_solo_fuertes():
    dbz = np.array([[0, 10, 30, 35, 54]], dtype=np.uint8)
    assert geo.mascara_dbz(dbz, 35).tolist() == [[0, 0, 0, 255, 255]]


def test_template_a_dbz_colores_de_paleta():
    rgb = np.array([[geo.DBZ_COLOR_MAP[35], geo.DBZ_COLOR_MAP[20], (0, 0, 0), (128, 128, 0)]],
                   dtype=np.uint8)
    assert geo.template_a_dbz(rgb).tolist() == [[35, 20, 0, 0]]


def test_elegir_umbral_respaldo_si_pocos_px():
    pocos = np.zeros((50, 50), np.uint8)
    pocos[:5, :5] = 45                     # 25 px fuertes
    pocos[10:40, 10:40] = 20
    assert geo.elegir_umbral(pocos) == geo.UMBRAL_DBZ_RESPALDO
    muchos = np.full((50, 50), 45, np.uint8)
    assert geo.elegir_umbral(muchos) == geo.UMBRAL_DBZ_MATCH


# ── Capa 2: ventana ───────────────────────────────────────────────────────────

def test_ventana_encuentra_eco_corrido(g, templates_sinteticos, eco_sintetico):
    t = templates_sinteticos[0]
    dbz = _imagen_con_ecos(g, eco_sintetico, dc=6, dr=-4)
    m = geo.buscar_en_ventana(geo.mascara_dbz(dbz, 35), t.mascara, g.ecos[t.nombre])
    assert m.corrimiento(g.ecos[t.nombre]) == (6, -4)
    assert m.score > 0.9


def test_ventana_ignora_senuelo_lejano(g, templates_sinteticos):
    """Reproduce el 13/10: lluvia fuerte lejos del eco no puede ganar."""
    t = templates_sinteticos[0]
    dbz = np.zeros((g.alto, g.ancho), np.uint8)
    dbz[520:700, 250:450] = 45                 # solo el señuelo, sin eco
    m = geo.buscar_en_ventana(geo.mascara_dbz(dbz, 35), t.mascara, g.ecos[t.nombre])
    assert m is None


def test_ventana_vacia_devuelve_none(g, templates_sinteticos):
    t = templates_sinteticos[0]
    vacia = np.zeros((g.alto, g.ancho), np.uint8)
    assert geo.buscar_en_ventana(vacia, t.mascara, g.ecos[t.nombre]) is None


# ── Capa 4: testigos ──────────────────────────────────────────────────────────

def test_combinar_consistente_promedia():
    estado, corr = geo.combinar_corrimientos([((6, -4), 0.8), ((8, -2), 0.7)])
    assert estado == "consistente" and corr == (7.0, -3.0)


def test_combinar_inconsistente():
    estado, corr = geo.combinar_corrimientos([((6, -4), 0.8), ((-15, 20), 0.7)])
    assert estado == "inconsistente" and corr == (0.0, 0.0)


def test_combinar_un_template():
    estado, corr = geo.combinar_corrimientos([((2, 1), 0.5), None])
    assert estado == "un_template" and corr == (2.0, 1.0)


def test_combinar_descarta_score_bajo():
    estado, _ = geo.combinar_corrimientos([((2, 1), 0.05), ((2, 1), 0.09)])
    assert estado == "sin_match"


# ── Capas 3+5: decisión ───────────────────────────────────────────────────────

def test_decidir_mueve_solo_con_dos_testigos():
    assert geo.decidir_corrimiento("consistente", (7.0, -3.0)) == ("corregido", (7.0, -3.0))
    assert geo.decidir_corrimiento("un_template", (7.0, -3.0)) == ("nominal_un_template", (0.0, 0.0))
    assert geo.decidir_corrimiento("inconsistente", (0.0, 0.0))[0] == "nominal_inconsistente"


def test_decidir_ignora_ruido():
    assert geo.decidir_corrimiento("consistente", (2.0, 1.0)) == ("nominal_consistente", (0.0, 0.0))


# ── Clutter, reproyección, salida ─────────────────────────────────────────────

def test_clutter_en_posicion_real_no_en_el_match(g, templates_sinteticos, eco_sintetico):
    """Con lluvia fuerte cerca, el clutter se borra donde está el eco y la lluvia queda."""
    dbz = _imagen_con_ecos(g, eco_sintetico, senuelo=True)
    estado, corr, _, _ = geo.estimar_corrimiento(dbz, templates_sinteticos, g)
    clutter = geo.mascara_clutter(dbz.shape, templates_sinteticos, g, corr)
    out = geo._apply_dbz_filters(dbz, np.zeros((*dbz.shape, 3), np.uint8), clutter)
    # el eco fijo desapareció...
    for t in templates_sinteticos:
        col, row = g.ecos[t.nombre]
        h, w = t.forma.shape
        assert not out[row:row + h, col:col + w][t.forma].any()
    # ...y la lluvia del señuelo sigue intacta
    assert (out[560:640, 300:400] == 40).all()


def test_reproyectar_nearest_no_inventa_niveles(g):
    rng = np.random.default_rng(0)
    niveles = np.array([0, 10, 35, 45, 54], np.uint8)
    dbz = niveles[rng.integers(0, len(niveles), (g.alto, g.ancho))]
    out, t, crs = geo.reproyectar(dbz, g.transform(), g.crs, "EPSG:3857")
    assert set(np.unique(out)) <= set(niveles.tolist())
    assert crs.to_epsg() == 3857


def test_reproyectar_none_devuelve_nativo(g):
    dbz = np.zeros((g.alto, g.ancho), np.uint8)
    out, t, crs = geo.reproyectar(dbz, g.transform(), g.crs, None)
    assert out is dbz and t == g.transform()


def test_geolocalizar_corrige_y_etiqueta(geometrias, g, templates_sinteticos, eco_sintetico):
    dbz = _imagen_con_ecos(g, eco_sintetico, dc=6, dr=-4)
    r = geo.geolocalizar(np.zeros((*dbz.shape, 3), np.uint8), dbz, geometrias=geometrias,
                         templates=templates_sinteticos,
                         crs_salida=None)
    assert r.estado_geo == "corregido" and r.corrimiento_px == (6.0, -4.0)
    with rasterio.open(io.BytesIO(r.geotiff_bytes)) as src:
        tags = src.tags()
        assert tags["GEO_ESTADO"] == "corregido"
        assert tags["GEO_VARIANTE"] == VARIANTE
        assert src.transform == g.transform(6, -4)
        assert src.colormap(1)[35][:3] == geo.DBZ_COLOR_MAP[35]


def test_geolocalizar_tamano_desconocido_usa_legado_marcado(monkeypatch, geometrias):
    """Banco de imágenes irregulares: sin variante → legado, marcado."""
    llamado = {}

    def falso_legado(filled_rgb, dbz_map):
        llamado["si"] = True
        return geo.GeoResultado(geotiff_bytes=b"", transform_affine="t", crs_str="EPSG:3857",
                                score_match=0.4, delta_lon=0.0, delta_lat=0.0,
                                estado_geo="legado_sin_calibrar")

    monkeypatch.setattr(geo, "_geolocalizar_legado", falso_legado)
    r = geo.geolocalizar(np.zeros((842, 761, 3), np.uint8), np.zeros((842, 761), np.uint8),
                         geometrias=geometrias)
    assert llamado["si"] and r.estado_geo == "legado_sin_calibrar"


def test_legado_etiqueta_geotiff():
    """El GeoTIFF del legado también lleva GEO_ESTADO para poder auditarlo."""
    b = geo.dbz_array_to_geotiff_bytes(np.zeros((5, 5), np.uint8), rasterio.transform.Affine.identity(),
                                       "EPSG:3857", etiquetas_geo={"GEO_ESTADO": "legado_sin_calibrar"})
    with rasterio.open(io.BytesIO(b)) as src:
        assert src.tags()["GEO_ESTADO"] == "legado_sin_calibrar"


def test_geometrias_inexistentes_devuelve_vacio(tmp_path):
    assert geo.cargar_geometrias(tmp_path / "no_existe.json") == {}


def test_templates_reales_cargan_a_35_dbz():
    if not (DIR_TEMPLATES / "template_eco_fijo.tif").exists():
        pytest.skip("sin templates/")
    for t in geo.cargar_templates(DIR_TEMPLATES):
        assert t.umbral == 35
        assert np.count_nonzero(t.mascara) >= geo.MIN_PX_MASCARA


# ── Regresión con datos reales (opcional) ─────────────────────────────────────

@pytest.mark.skipif(not os.environ.get("GEO_TIF_DIR"), reason="definir GEO_TIF_DIR")
def test_regresion_noche_13_10(geometrias):
    """Ningún frame de la noche del 13/10 puede salir corrido.

    Entrada: TIF de salida del legado (560×741). Su dBZ ya está en la grilla de la variante.
    """
    tifs = sorted(Path(os.environ["GEO_TIF_DIR"]).glob("radar_*.tif"))
    assert len(tifs) >= 189
    templates = geo.cargar_templates(DIR_TEMPLATES)
    for tif in tifs:
        with rasterio.open(tif) as src:
            dbz = src.read(1)
        estado, corr, _, _ = geo.estimar_corrimiento(dbz, templates, geometrias[VARIANTE])
        assert corr == (0.0, 0.0), f"{tif.name}: {estado} {corr}"


# ── Calibrador ────────────────────────────────────────────────────────────────

def test_calibrador_recupera_geometria_sintetica(g):
    """Dibuja un límite con geometría conocida y el calibrador tiene que recuperarla."""
    import cv2
    import calibrar_geometria_gif as cg

    rng = np.random.default_rng(1)
    t = np.linspace(0, 2 * np.pi, 90, endpoint=False)
    lon = -68.6 + 2.0 * np.cos(t) * (1 + 0.08 * rng.standard_normal(90))
    lat = -34.8 + 2.8 * np.sin(t) * (1 + 0.08 * rng.standard_normal(90))
    anillo = np.vstack([np.column_stack([lon, lat]), [[lon[0], lat[0]]]])

    xy_dibujo = cg.densificar_en_metros([anillo], cg.crs_aeqd(), 200)
    c, r = cg.a_pixeles(xy_dibujo, g.pixel_m, g.c0, g.r0)
    lineas = np.zeros((g.alto, g.ancho), np.uint8)
    cv2.polylines(lineas, [np.round(np.column_stack([c, r])).astype(np.int32)], True, 255, 1)

    D = cg.transformada_distancia(lineas > 0)
    cal = cg.ajustar(D, cg.densificar_en_metros([anillo], cg.crs_aeqd()), cero_km=(200, 338))
    assert cal.pixel_m == pytest.approx(g.pixel_m, rel=0.002)
    assert cal.c0 == pytest.approx(g.c0, abs=0.5)
    assert cal.r0 == pytest.approx(g.r0, abs=0.5)
    ecos, dif = cg.trasladar_ecos(g, cal)
    assert dif < 0.01 and ecos == {k: list(v) for k, v in g.ecos.items()}
