"""
F0 — Verifica si hay imágenes consecutivas con el mismo contenido.

Para cada imagen completada compara, contra la anterior:
  - raw_bytes : hash de los bytes del archivo original (raw_data)
  - raw_pix   : hash de los PÍXELES del original (ignora metadatos/compresión)
  - geotiff   : hash del GeoTIFF final
  - dif_pix   : % de píxeles distintos entre los originales

Si raw_bytes difiere pero raw_pix coincide, son archivos distintos con la
misma imagen adentro (p. ej. el mismo escaneo descargado dos veces).

Exporta los pares sospechosos lado a lado a salidas_f0/duplicados/.

Uso (desde la raíz del repo):
    uv run python scripts/f0_duplicados.py
    uv run python scripts/f0_duplicados.py --desde "2025-01-06 15:00" --hasta "2025-01-06 19:00"
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from f0_inventario import _db_url_sync  # noqa: E402


def _md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()[:10]


def _pixeles(raw: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"))


def cargar(desde, hasta):
    import psycopg2

    sql = """SELECT id, fecha_hora, raw_data, geotiff_data, tiene_marco
             FROM radar.imagenes_radar
             WHERE estado = 'completado' AND raw_data IS NOT NULL"""
    params = []
    if desde:
        sql += " AND fecha_hora >= %s"
        params.append(desde)
    if hasta:
        sql += " AND fecha_hora < %s"
        params.append(hasta)
    sql += " ORDER BY fecha_hora"
    try:
        conn = psycopg2.connect(_db_url_sync())
    except psycopg2.OperationalError as exc:
        sys.exit(f"No pude conectar a la base. ¿docker compose up db -d?\n{exc}")
    with conn, conn.cursor(name="dup") as cur:
        cur.itersize = 20
        cur.execute(sql, params)
        for r in cur:
            yield r[0], r[1], bytes(r[2]), bytes(r[3]) if r[3] else b"", r[4]


def comparar(filas):
    """filas: iterable de (id, fecha, raw, geotiff, tiene_marco). Devuelve lista de dicts."""
    out, prev = [], None
    for img_id, fecha, raw, geo, marco in filas:
        pix = _pixeles(raw)
        fila = {
            "id": img_id, "fecha_hora": fecha, "tiene_marco": marco,
            "tam_bytes": len(raw), "shape": "x".join(map(str, pix.shape[:2])),
            "raw_bytes": _md5(raw), "raw_pix": _md5(pix.tobytes()), "geotiff": _md5(geo),
            "igual_raw_bytes": "", "igual_raw_pix": "", "igual_geotiff": "", "dif_pix_pct": "",
            "_pix": pix, "_raw": raw,
        }
        if prev is not None:
            fila["igual_raw_bytes"] = fila["raw_bytes"] == prev["raw_bytes"]
            fila["igual_raw_pix"] = fila["raw_pix"] == prev["raw_pix"]
            fila["igual_geotiff"] = fila["geotiff"] == prev["geotiff"]
            if pix.shape == prev["_pix"].shape:
                dif = np.any(pix != prev["_pix"], axis=2).mean() * 100
                fila["dif_pix_pct"] = round(float(dif), 3)
        out.append(fila)
        if prev is not None:
            prev.pop("_pix", None)
        prev = fila
    return out


def exportar_par(dir_: Path, a: dict, b: dict):
    dir_.mkdir(parents=True, exist_ok=True)
    ia = Image.open(io.BytesIO(a["_raw"])).convert("RGB")
    ib = Image.open(io.BytesIO(b["_raw"])).convert("RGB")
    lienzo = Image.new("RGB", (ia.width + ib.width + 10, max(ia.height, ib.height)), "white")
    lienzo.paste(ia, (0, 0))
    lienzo.paste(ib, (ia.width + 10, 0))
    nombre = f"{a['fecha_hora']:%H%M}_id{a['id']}__{b['fecha_hora']:%H%M}_id{b['id']}.png"
    lienzo.save(dir_ / nombre)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde")
    ap.add_argument("--hasta")
    ap.add_argument("--salida", default="salidas_f0")
    a = ap.parse_args()

    filas = comparar(cargar(a.desde, a.hasta))
    if not filas:
        sys.exit("No hay imágenes completadas en ese rango.")
    out = Path(a.salida)
    out.mkdir(parents=True, exist_ok=True)

    campos = [k for k in filas[0] if not k.startswith("_")]
    with open(out / "duplicados.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)

    pares = [(filas[i - 1], filas[i]) for i in range(1, len(filas))
             if filas[i]["igual_geotiff"] or filas[i]["igual_raw_pix"]]
    for p, c in pares:
        if "_raw" in p:
            exportar_par(out / "duplicados", p, c)

    n_bytes = sum(1 for f in filas if f["igual_raw_bytes"] is True)
    n_pix = sum(1 for f in filas if f["igual_raw_pix"] is True)
    n_geo = sum(1 for f in filas if f["igual_geotiff"] is True)
    print("=" * 60)
    print(f"Imágenes: {len(filas)}")
    print(f"Consecutivas con mismo ARCHIVO (bytes):   {n_bytes}")
    print(f"Consecutivas con mismos PÍXELES (raw):    {n_pix}")
    print(f"Consecutivas con mismo GeoTIFF:           {n_geo}")
    for p, c in pares:
        print(f"  id {p['id']:>4} {p['fecha_hora']:%H:%M}  ->  id {c['id']:>4} {c['fecha_hora']:%H:%M} | "
              f"bytes {'=' if c['igual_raw_bytes'] else '≠'} | píxeles {'=' if c['igual_raw_pix'] else '≠'} "
              f"({c['dif_pix_pct']}% distintos) | geotiff {'=' if c['igual_geotiff'] else '≠'} | "
              f"marco={c['tiene_marco']}")
    print(f"CSV: {(out / 'duplicados.csv').resolve()}")
    if pares:
        print(f"Pares lado a lado: {(out / 'duplicados').resolve()}")
    print("=" * 60)


if __name__ == "__main__":
    main()
