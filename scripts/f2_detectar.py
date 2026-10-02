"""
F2 — Detectar celdas en imágenes de la base y exportarlas para revisar en QGIS.

No escribe en la base. Por cada imagen completada del rango:
  1. Lee geotiff_data, lo reproyecta a la grilla 5344 (src/subsistema2/raster.py).
  2. Detecta celdas (src/subsistema2/detector.py) con los parámetros de config.py.
  3. Exporta en salidas_f2/:
       dbz_5344/<AAAAMMDD_HHMM>.tif   raster reproyectado (lo que ve el detector)
       celdas.geojson                 polígonos (EPSG:4326, un feature por celda)
       centroides.geojson             centroides ponderados por Z
       celdas.csv                     atributos de todas las celdas

En QGIS: arrastrar el .tif y los .geojson. Para comparar áreas, en la tabla de
atributos de celdas.geojson calcular $area con el elipsoide WGS84 (o
reproyectar la capa a EPSG:5344) y comparar con area_km2.

Uso (desde la raíz del repo, con la base levantada: docker compose up db -d):
    uv run python scripts/f2_detectar.py --desde "2025-01-06 17:00" --hasta "2025-01-06 17:30"
    uv run python scripts/f2_detectar.py --imagen-id 39
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import rasterio
from rasterio.warp import transform_geom

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from f0_inventario import _db_url_sync  # noqa: E402  (misma conexión que F0)

# src.config exige estas variables aunque acá no se usen
os.environ.setdefault("DATABASE_URL", _db_url_sync())
os.environ.setdefault("SECRET_KEY", "solo-para-scripts-de-analisis")

from src.subsistema2.detector import ParametrosDeteccion, detectar  # noqa: E402
from src.subsistema2.raster import Grilla, cargar_en_grilla  # noqa: E402

CAMPOS = ["imagen_id", "fecha_hora", "numero", "n_pixeles", "area_km2", "area_nucleo_km2",
          "n_nucleos", "dbz_max", "dbz_medio", "x_m", "y_m", "lon", "lat",
          "elongacion", "orientacion_deg"]


def cargar(desde: str | None, hasta: str | None, imagen_id: int | None):
    import psycopg2

    sql = ("SELECT id, fecha_hora, geotiff_data FROM radar.imagenes_radar "
           "WHERE estado = 'completado' AND geotiff_data IS NOT NULL")
    params: list = []
    if imagen_id is not None:
        sql += " AND id = %s"
        params.append(imagen_id)
    if desde:
        sql += " AND fecha_hora >= %s"
        params.append(desde)
    if hasta:
        sql += " AND fecha_hora < %s"
        params.append(hasta)
    url = _db_url_sync()
    try:
        conn = psycopg2.connect(url)
    except psycopg2.OperationalError as exc:
        sys.exit(f"No pude conectar a la base ({url.split('@')[-1]}). "
                 f"¿Está levantada? -> docker compose up db -d\n{exc}")
    with conn, conn.cursor() as cur:
        cur.execute(sql + " ORDER BY fecha_hora", params)
        for i, f, g in cur:
            yield i, f, bytes(g)


def _wkt_a_geojson(wkt: str) -> dict:
    """MULTIPOLYGON WKT (como lo arma el detector) → geometría GeoJSON."""
    cuerpo = wkt[len("MULTIPOLYGON("):-1]
    polys = []
    for p in cuerpo.split(")), (("):
        anillos = []
        for r in p.strip("()").split("), ("):
            anillos.append([[float(v) for v in par.split()] for par in r.strip("()").split(", ")])
        polys.append(anillos)
    return {"type": "MultiPolygon", "coordinates": polys}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desde", help="YYYY-MM-DD[ HH:MM]")
    ap.add_argument("--hasta", help="YYYY-MM-DD[ HH:MM] (exclusivo)")
    ap.add_argument("--imagen-id", type=int)
    ap.add_argument("--salida", default="salidas_f2")
    args = ap.parse_args()

    grilla, params = Grilla.desde_settings(), ParametrosDeteccion.desde_settings()
    out = Path(args.salida)
    (out / "dbz_5344").mkdir(parents=True, exist_ok=True)
    poligonos, puntos, filas = [], [], []

    print(f"Parámetros: {params.como_dict()} | grilla {grilla.ancho}×{grilla.alto} "
          f"de {grilla.resolucion_m:.0f} m en EPSG:{grilla.srid}")
    n_img = 0
    for img_id, fecha, data in cargar(args.desde, args.hasta, args.imagen_id):
        n_img += 1
        raster = cargar_en_grilla(data, grilla)
        res = detectar(raster, params)
        with rasterio.open(out / "dbz_5344" / f"{fecha:%Y%m%d_%H%M}.tif", "w", driver="GTiff",
                           height=grilla.alto, width=grilla.ancho, count=1, dtype="uint8",
                           crs=grilla.crs, transform=grilla.transform, nodata=0, compress="lzw") as dst:
            dst.write(raster.datos, 1)

        area_total = sum(c.area_km2 for c in res.celdas)
        mayor = max(res.celdas, key=lambda c: c.area_km2, default=None)
        print(f"  {fecha:%Y-%m-%d %H:%M} (id {img_id}): {len(res.celdas):3d} celdas, "
              f"{res.n_descartadas:3d} descartadas < {params.area_min_km2} km², "
              f"área total {area_total:7.1f} km²"
              + (f", mayor {mayor.area_km2:.0f} km² / {mayor.dbz_max} dBZ" if mayor else ""))

        for c in res.celdas:
            fila = {"imagen_id": img_id, "fecha_hora": fecha.isoformat(sep=" ")}
            fila.update({k: getattr(c, k) for k in CAMPOS[2:]})
            filas.append(fila)
            geom = transform_geom(grilla.crs, "EPSG:4326", _wkt_a_geojson(c.poligono_wkt), precision=6)
            poligonos.append({"type": "Feature", "geometry": geom, "properties": fila})
            puntos.append({"type": "Feature", "properties": fila,
                           "geometry": {"type": "Point", "coordinates": [round(c.lon, 6), round(c.lat, 6)]}})

    if n_img == 0:
        sys.exit("No hay imágenes completadas con geotiff_data para ese filtro.")
    for nombre, feats in (("celdas.geojson", poligonos), ("centroides.geojson", puntos)):
        (out / nombre).write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    with open(out / "celdas.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(filas)
    print(f"\n{n_img} imágenes, {len(filas)} celdas → {out}/")


if __name__ == "__main__":
    main()
