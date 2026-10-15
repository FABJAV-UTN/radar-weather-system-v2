"""
calibrar_geometria_gif.py — Calibra la geometría de UNA variante de GIF del DACC.

Se corre una vez por variante (tamaño de recorte), fuera del pipeline, y
agrega/actualiza la entrada en geometrias_gif.json.

Pasos (informe_geo_robusto.tex, "Herramienta de calibración"):
  1. Recorta el GIF crudo con crop_imagen (misma grilla que el TIF).
  2. Extrae las líneas de límites dibujadas en el GIF: RGB (64,48,0) y (64,0,0).
  3. Proyecta el límite de Mendoza (Natural Earth admin1, GeoJSON) a AEQD.
  4. Busca escala s y posición del 0 km (c0, r0) que minimizan el costo chamfer
         C = mean( min( D(π(λ,φ)), 15 ) )
     en una grilla gruesa y refina con Nelder–Mead.
  5. Traslada la posición de los templates desde la variante de referencia
     pasando por metros, y avisa si las escalas no coinciden (los templates se
     usan en resolución nativa).

Uso (desde la raíz del repo; Natural Earth en GeoJSON, ej. ne_10m_admin_1_states_provinces.geojson):

    uv run python scripts/calibrar_geometria_gif.py \\
        --gif ruta/al/crudo.gif \\
        --natural-earth ruta/ne_10m_admin_1_states_provinces.geojson \\
        [--cero-km 204.5 342.9]   # opcional: lectura de los ejes, acota la búsqueda
        [--guardar]               # escribe en templates/geometrias_gif.json

Sin --guardar solo muestra el resultado.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from rasterio.crs import CRS
from rasterio.warp import transform as transformar_coords
from scipy.ndimage import map_coordinates
from scipy.optimize import minimize

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from src.subsistema1 import geolocalizar as geo  # noqa: E402

RUTA_GEOMETRIAS = RAIZ / "templates" / geo.NOMBRE_GEOMETRIAS

# Centro del radar DACC (centro de la proyección AEQD)
LAT0, LON0 = -33.4917, -69.0217
COLORES_LIMITES = ((64, 48, 0), (64, 0, 0))   # departamental, provincial
TOL_COLOR = 12
TRUNCAMIENTO_PX = 15.0
PASO_LIMITE_M = 1000.0                          # un punto cada ~1 km
VARIANTE_REF = "dacc_scheduler_560x741"


@dataclass
class Calibracion:
    pixel_m: float
    c0: float
    r0: float
    costo: float
    mediana_px: float
    p90_px: float


# ── 1-2. Imagen y líneas ──────────────────────────────────────────────────────

def cargar_recorte(ruta_gif: Path, sin_crop: bool = False) -> np.ndarray:
    from PIL import Image

    img = Image.open(ruta_gif)
    if sin_crop:
        if getattr(img, "is_animated", False):
            img.seek(0)
        return np.array(img.convert("RGB"))
    from src.subsistema1.crop import crop_imagen
    return crop_imagen(img)


def mascara_lineas(rgb: np.ndarray, colores=COLORES_LIMITES, tol: int = TOL_COLOR) -> np.ndarray:
    """bool (H, W): píxeles de las líneas de límites."""
    a = rgb[:, :, :3].astype(np.int16)
    m = np.zeros(a.shape[:2], dtype=bool)
    for c in colores:
        m |= np.all(np.abs(a - np.array(c, np.int16)) <= tol, axis=2)
    return m


def transformada_distancia(lineas: np.ndarray) -> np.ndarray:
    """D(r, c): distancia en px a la línea más cercana."""
    fondo = np.where(lineas, 0, 255).astype(np.uint8)
    return cv2.distanceTransform(fondo, cv2.DIST_L2, 5).astype(np.float32)


# ── 3. Límite de Mendoza ──────────────────────────────────────────────────────

def crs_aeqd(lat0: float = LAT0, lon0: float = LON0) -> CRS:
    return CRS.from_proj4(f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +datum=WGS84 +units=m +no_defs")


def limite_mendoza(ruta_geojson: Path, provincia: str = "Mendoza") -> list[np.ndarray]:
    """Anillos (lon, lat) de la provincia en el GeoJSON de Natural Earth."""
    datos = json.loads(Path(ruta_geojson).read_text(encoding="utf-8"))
    for f in datos["features"]:
        p = f["properties"]
        if p.get("name") == provincia and p.get("admin", "Argentina") == "Argentina":
            geom = f["geometry"]
            polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
            return [np.asarray(anillo, dtype=float)[:, :2] for poly in polys for anillo in poly]
    raise ValueError(f"No encontré '{provincia}' en {ruta_geojson}")


def densificar_en_metros(anillos_lonlat: list[np.ndarray], crs: CRS,
                         paso: float = PASO_LIMITE_M) -> np.ndarray:
    """Proyecta a AEQD y re-muestrea cada anillo con un punto cada `paso` m. → (N, 2) x, y."""
    puntos = []
    for anillo in anillos_lonlat:
        xs, ys = transformar_coords("EPSG:4326", crs, anillo[:, 0].tolist(), anillo[:, 1].tolist())
        xy = np.column_stack([xs, ys])
        seg = np.diff(xy, axis=0)
        largo = np.hypot(seg[:, 0], seg[:, 1])
        acum = np.concatenate([[0], np.cumsum(largo)])
        if acum[-1] == 0:
            continue
        t = np.arange(0, acum[-1], paso)
        puntos.append(np.column_stack([np.interp(t, acum, xy[:, 0]), np.interp(t, acum, xy[:, 1])]))
    return np.vstack(puntos)


# ── 4. Ajuste chamfer ─────────────────────────────────────────────────────────

def a_pixeles(xy: np.ndarray, s: float, c0: float, r0: float) -> tuple[np.ndarray, np.ndarray]:
    """Metros AEQD → (col, fila) de centro de píxel."""
    return c0 + xy[:, 0] / s, r0 - xy[:, 1] / s


def distancias(D: np.ndarray, xy: np.ndarray, s: float, c0: float, r0: float) -> np.ndarray:
    col, fila = a_pixeles(xy, s, c0, r0)
    d = map_coordinates(D, [fila, col], order=1, mode="constant", cval=TRUNCAMIENTO_PX)
    return np.minimum(d, TRUNCAMIENTO_PX)


def costo(D, xy, s, c0, r0) -> float:
    return float(distancias(D, xy, s, c0, r0).mean())


def ajustar(D: np.ndarray, xy: np.ndarray, cero_km: tuple[float, float] | None = None,
            escalas=np.arange(600.0, 960.0, 5.0)) -> Calibracion:
    alto, ancho = D.shape
    if cero_km is not None:
        cs = np.arange(cero_km[0] - 20, cero_km[0] + 21, 2.0)
        rs = np.arange(cero_km[1] - 20, cero_km[1] + 21, 2.0)
    else:
        cs = np.arange(0, ancho, 8.0)
        rs = np.arange(0, alto, 8.0)
    gruesos = xy[:: max(1, len(xy) // 400)]           # submuestreo para la grilla gruesa
    mejor = (np.inf, None)
    for s in escalas:
        for c0 in cs:
            for r0 in rs:
                k = costo(D, gruesos, s, c0, r0)
                if k < mejor[0]:
                    mejor = (k, (s, c0, r0))
    res = minimize(lambda p: costo(D, xy, *p), x0=np.array(mejor[1]), method="Nelder-Mead",
                   options={"xatol": 1e-3, "fatol": 1e-4, "maxiter": 4000})
    s, c0, r0 = res.x
    d = distancias(D, xy, s, c0, r0)
    return Calibracion(float(s), float(c0), float(r0), float(res.fun),
                       float(np.median(d)), float(np.percentile(d, 90)))


# ── 5. Trasladar templates ────────────────────────────────────────────────────

def trasladar_ecos(ref: geo.Geometria, cal: Calibracion) -> tuple[dict[str, list[int]], float]:
    """Posición de los templates en la nueva variante, pasando por metros.

    Devuelve (ecos_px, diferencia_relativa_de_escala).
    """
    ecos = {}
    for nombre, (col, row) in ref.ecos.items():
        x = (col - ref.c0) * ref.pixel_m
        y = -(row - ref.r0) * ref.pixel_m
        c, r = a_pixeles(np.array([[x, y]]), cal.pixel_m, cal.c0, cal.r0)
        ecos[nombre] = [int(round(c[0])), int(round(r[0]))]
    return ecos, abs(cal.pixel_m - ref.pixel_m) / ref.pixel_m


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gif", type=Path, required=True)
    ap.add_argument("--natural-earth", type=Path, required=True)
    ap.add_argument("--cero-km", type=float, nargs=2, metavar=("COL", "FILA"))
    ap.add_argument("--sin-crop", action="store_true", help="la imagen ya está recortada")
    ap.add_argument("--nombre", help="nombre de la variante (default: dacc_<ancho>x<alto>)")
    ap.add_argument("--guardar", action="store_true")
    args = ap.parse_args(argv)

    rgb = cargar_recorte(args.gif, args.sin_crop)
    alto, ancho = rgb.shape[:2]
    lineas = mascara_lineas(rgb)
    print(f"Recorte {ancho}×{alto}, {int(lineas.sum())} px de línea de límites")

    xy = densificar_en_metros(limite_mendoza(args.natural_earth), crs_aeqd())
    cal = ajustar(transformada_distancia(lineas), xy, tuple(args.cero_km) if args.cero_km else None)
    print(f"pixel = {cal.pixel_m:.2f} m | 0 km en ({cal.c0:.1f}; {cal.r0:.1f}) | "
          f"costo {cal.costo:.2f} px, mediana {cal.mediana_px:.2f}, p90 {cal.p90_px:.1f}")

    geometrias = geo.cargar_geometrias(RUTA_GEOMETRIAS)
    ecos, dif = trasladar_ecos(geometrias[VARIANTE_REF], cal)
    print(f"ecos trasladados: {ecos}")
    if dif > 0.01:
        print(f"ATENCIÓN: la escala difiere {dif:.1%} de la variante de referencia. "
              "Los templates se usan en resolución nativa: hay que recortar templates nuevos "
              "de esta variante antes de confiar en el matching.")

    if args.guardar:
        nombre = args.nombre or f"dacc_{ancho}x{alto}"
        datos = json.loads(RUTA_GEOMETRIAS.read_text(encoding="utf-8"))
        datos["variantes"][nombre] = {
            "ancho": ancho, "alto": alto,
            "pixel_m": round(cal.pixel_m, 2),
            "cero_km_px": [round(cal.c0, 1), round(cal.r0, 1)],
            "centro_aeqd": {"lat": LAT0, "lon": LON0},
            "ecos_px": ecos,
            "calibracion": {
                "fuente": str(args.gif.name),
                "limite_mendoza": f"chamfer: costo {cal.costo:.2f} px, mediana "
                                  f"{cal.mediana_px:.2f} px, p90 {cal.p90_px:.1f} px",
            },
        }
        RUTA_GEOMETRIAS.write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n",
                                               encoding="utf-8")
        print(f"Guardado como '{nombre}' en {RUTA_GEOMETRIAS.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
