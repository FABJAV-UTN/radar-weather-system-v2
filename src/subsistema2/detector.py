# src/subsistema2/detector.py
"""
Detección de celdas convectivas (F2).

    dBZ en la grilla 5344 ──► umbral D1 ──► componentes conexas D4 ──►
    filtro de área D3 ──► atributos por celda (D2, D6) ──► polígonos

Una celda es un grupo de píxeles vecinos con dBZ ≥ umbral (enfoque TITAN /
TINT, manual cap. 5). Por cada celda se calcula:
  - área real (píxeles × área del píxel en EPSG:5344) y área del núcleo ≥ D2;
  - dBZ máximo y dBZ medio promediado en Z lineal (promediar dBZ subestima);
  - centroide ponderado por Z = 10^(dBZ/10) (D6) y centroide geométrico;
  - lon/lat del centroide, bounding box, elongación y orientación;
  - el contorno como MULTIPOLYGON (WKT), listo para PostGIS.

No toca la base ni lee configuración por su cuenta: recibe un RasterDBZ y
unos ParametrosDeteccion. Así se prueba con numpy puro.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from rasterio import features
from rasterio.warp import transform as transformar_puntos
from scipy import ndimage as ndi

from src.subsistema2.modelos import Celda
from src.subsistema2.raster import RasterDBZ

VERSION_DETECTOR = "f2-1.0"


@dataclass(frozen=True)
class ParametrosDeteccion:
    """D1–D4 del plan. Se guardan tal cual en ejecuciones_tracking.parametros."""

    umbral_dbz: float = 35.0
    umbral_nucleo_dbz: float = 45.0
    area_min_km2: float = 4.0
    conectividad: int = 8

    def __post_init__(self) -> None:
        if self.conectividad not in (4, 8):
            raise ValueError("conectividad debe ser 4 u 8")
        if self.umbral_nucleo_dbz < self.umbral_dbz:
            raise ValueError("el umbral de núcleo (D2) no puede ser menor que el de celda (D1)")
        if self.area_min_km2 < 0:
            raise ValueError("el área mínima no puede ser negativa")

    def como_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def desde_settings(cls) -> ParametrosDeteccion:
        from src.config import settings  # import diferido: el cálculo no exige .env

        return cls(
            umbral_dbz=settings.s2_umbral_dbz,
            umbral_nucleo_dbz=settings.s2_umbral_nucleo_dbz,
            area_min_km2=settings.s2_area_min_km2,
            conectividad=settings.s2_conectividad,
        )


@dataclass
class ResultadoDeteccion:
    """Celdas de una imagen y la matriz de etiquetas (0 = fondo, k = celda k)."""

    celdas: list[Celda]
    etiquetas: np.ndarray
    raster: RasterDBZ
    n_descartadas: int          # componentes por debajo del área mínima


def _estructura(conectividad: int) -> np.ndarray:
    return np.ones((3, 3), bool) if conectividad == 8 else ndi.generate_binary_structure(2, 1)


def _validar_crs(raster: RasterDBZ) -> None:
    crs = raster.crs
    if crs is None or crs.is_geographic:
        raise ValueError("El raster tiene que estar en un CRS proyectado en metros")
    if crs.to_epsg() == 3857:
        raise ValueError("El raster está en EPSG:3857: reproyectalo a la grilla 5344 antes "
                         "(en 3857 las áreas salen ~45 % más grandes)")


def _poligonos_wkt(etiquetas: np.ndarray, raster: RasterDBZ, n: int) -> list[str]:
    """
    Contorno de cada etiqueta como MULTIPOLYGON WKT.

    Se vectoriza con conectividad 4 a propósito: dos píxeles de la misma celda
    que solo se tocan en diagonal quedan como dos polígonos de una misma
    multiparte (válido en OGC). Con 8 saldría un anillo que se toca a sí mismo.
    """
    partes: list[list[list]] = [[] for _ in range(n + 1)]
    for geom, valor in features.shapes(
        etiquetas.astype(np.int32), mask=etiquetas > 0, connectivity=4, transform=raster.transform
    ):
        partes[int(valor)].append(geom["coordinates"])

    def anillo(coords) -> str:
        return "(" + ", ".join(f"{x:.2f} {y:.2f}" for x, y in coords) + ")"

    def poligono(rings) -> str:
        return "(" + ", ".join(anillo(r) for r in rings) + ")"

    return ["MULTIPOLYGON(" + ", ".join(poligono(p) for p in partes[k]) + ")" for k in range(1, n + 1)]


def detectar(raster: RasterDBZ, params: ParametrosDeteccion | None = None) -> ResultadoDeteccion:
    """Detecta las celdas de un raster de dBZ ya reproyectado a la grilla de cálculo."""
    params = params or ParametrosDeteccion()
    _validar_crs(raster)

    dbz = raster.datos.astype(np.float64)
    T = raster.transform
    area_px_km2 = abs(T.a * T.e - T.b * T.d) / 1e6
    estructura = _estructura(params.conectividad)

    # ── 1. Umbral (D1) y componentes conexas (D4) ────────────────────────────
    mascara = dbz >= params.umbral_dbz
    etiquetas, n = ndi.label(mascara, structure=estructura)
    vacio = ResultadoDeteccion([], np.zeros_like(etiquetas, dtype=np.int32), raster, 0)
    if n == 0:
        return vacio

    # ── 2. Área mínima (D3) y renumeración consecutiva 1..m ──────────────────
    n_px = np.bincount(etiquetas.ravel(), minlength=n + 1)
    validas = np.flatnonzero(n_px * area_px_km2 >= params.area_min_km2)
    validas = validas[validas > 0]
    n_descartadas = n - len(validas)
    if len(validas) == 0:
        vacio.n_descartadas = n_descartadas
        return vacio
    nuevo = np.zeros(n + 1, dtype=np.int32)
    nuevo[validas] = np.arange(1, len(validas) + 1, dtype=np.int32)
    etiquetas = nuevo[etiquetas]
    m = len(validas)

    # ── 3. Sumas por celda en un solo recorrido (bincount) ───────────────────
    lab = etiquetas.ravel()
    sel = lab > 0
    lab = lab[sel]
    filas, cols = np.indices(etiquetas.shape)
    f = filas.ravel()[sel] + 0.5          # centro del píxel
    c = cols.ravel()[sel] + 0.5
    d = dbz.ravel()[sel]
    z = 10.0 ** (d / 10.0)

    def suma(w=None):
        return np.bincount(lab, weights=w, minlength=m + 1)[1:]

    npx = suma().astype(np.int64)
    sz = suma(z)
    zc, zf = suma(z * c) / sz, suma(z * f) / sz              # centroide ponderado (píxeles)
    gc, gf = suma(c) / npx, suma(f) / npx                    # centroide geométrico
    # + 1/12: varianza de un píxel cuadrado (sin esto, una fila de píxeles da λ2 = 0)
    var_c = suma(c * c) / npx - gc**2 + 1 / 12
    var_f = suma(f * f) / npx - gf**2 + 1 / 12
    cov_cf = suma(c * f) / npx - gc * gf
    dbz_max = ndi.maximum(dbz, etiquetas, index=np.arange(1, m + 1)).astype(int)
    dbz_medio = 10.0 * np.log10(sz / npx)

    # Núcleos (D2): área y cantidad de componentes ≥ D2 dentro de cada celda
    nucleo = (dbz >= params.umbral_nucleo_dbz) & (etiquetas > 0)
    px_nucleo = np.bincount(etiquetas[nucleo], minlength=m + 1)[1:]
    et_nuc, n_nuc = ndi.label(nucleo, structure=estructura)
    n_nucleos = np.zeros(m, dtype=int)
    if n_nuc:
        # cada núcleo cae entero dentro de una celda (es un subconjunto conexo)
        celda_de_nucleo = ndi.maximum(etiquetas, et_nuc, index=np.arange(1, n_nuc + 1)).astype(int)
        n_nucleos = np.bincount(celda_de_nucleo, minlength=m + 1)[1:]

    # ── 4. Píxeles → metros con la transformación afín ───────────────────────
    def a_metros(cc, ff):
        return T.a * cc + T.b * ff + T.c, T.d * cc + T.e * ff + T.f

    x_z, y_z = a_metros(zc, zf)
    x_g, y_g = a_metros(gc, gf)
    lons, lats = transformar_puntos(raster.crs, "EPSG:4326", list(x_z), list(y_z))
    A = np.array([[T.a, T.b], [T.d, T.e]])
    cajas = ndi.find_objects(etiquetas)
    poligonos = _poligonos_wkt(etiquetas, raster, m)

    celdas: list[Celda] = []
    for k in range(m):
        # Forma: covarianza de las posiciones en metros (x este, y norte)
        cov = A @ np.array([[var_c[k], cov_cf[k]], [cov_cf[k], var_f[k]]]) @ A.T
        vals, vecs = np.linalg.eigh(cov)
        l2, l1 = vals
        vx, vy = vecs[:, 1]
        elong = float(np.sqrt(l1 / l2))
        orient = float(np.degrees(np.arctan2(vx, vy)) % 180.0)

        sf, sc = cajas[k]
        xs, ys = zip(*(a_metros(cc, ff) for cc in (sc.start, sc.stop) for ff in (sf.start, sf.stop)))
        medio = round(float(dbz_medio[k]), 2)

        celdas.append(Celda(
            numero=k + 1,
            n_pixeles=int(npx[k]),
            area_km2=round(float(npx[k] * area_px_km2), 4),
            area_nucleo_km2=round(float(px_nucleo[k] * area_px_km2), 4),
            n_nucleos=int(n_nucleos[k]),
            dbz_max=int(dbz_max[k]),
            dbz_medio=min(medio, float(dbz_max[k])),   # evita 45.000001 > 45 por redondeo
            x_m=float(x_z[k]), y_m=float(y_z[k]),
            lon=float(lons[k]), lat=float(lats[k]),
            x_geom_m=float(x_g[k]), y_geom_m=float(y_g[k]),
            bbox=(float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))),
            poligono_wkt=poligonos[k],
            elongacion=round(elong, 3),
            orientacion_deg=round(orient, 1),
        ))

    return ResultadoDeteccion(celdas=celdas, etiquetas=etiquetas, raster=raster,
                              n_descartadas=n_descartadas)
