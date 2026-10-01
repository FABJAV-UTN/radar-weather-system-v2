"""
F0 — Inventario de eventos y deriva de georreferenciación (Subsistema 2).

Lee radar.imagenes_radar (estado = 'completado'), abre cada GeoTIFF desde
geotiff_data (transform exacto, NO la columna transform_affine que está
redondeada) y reporta:

  - CRS y tamaño de píxel (nominal y real en el terreno)
  - Δt mediano y huecos > MAX_GAP_MIN
  - Deriva de la georreferenciación entre imágenes consecutivas (m)
  - Eventos candidatos: imágenes seguidas con dBZ ≥ UMBRAL_DBZ, sin huecos
    > MAX_GAP_MIN y con al menos MIN_IMAGENES imágenes

Salida en salidas_f0/: eventos.csv, imagenes.csv, huecos.csv

Uso (desde la raíz del repo):
    uv run python scripts/f0_inventario.py
    uv run python scripts/f0_inventario.py --desde 2025-01-05 --hasta 2025-01-07
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import math
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

import numpy as np
import rasterio
from rasterio.io import MemoryFile

# ── Parámetros (coinciden con D1, D8, D11 del plan) ──────────────────────────
UMBRAL_DBZ = 35.0
MAX_GAP_MIN = 12.0
MIN_IMAGENES = 3
NODATA_DBZ = 0  # valores <= esto se consideran sin eco

# Radio de la Tierra usado por EPSG:3857
_R_3857 = 6378137.0


@dataclass
class InfoImagen:
    id: int
    fecha_hora: datetime
    crs: str
    ancho: int
    alto: int
    pix_x: float              # unidades del CRS
    pix_y: float
    origen_x: float
    origen_y: float
    lat_centro: float
    pix_real_m: float         # tamaño real en el terreno
    dbz_max: float
    pix_ge_umbral: int
    score_match: float | None
    dt_min: float | None = None
    deriva_m: float | None = None
    cambio_escala_pct: float | None = None
    evento: int | None = None


@dataclass
class Evento:
    n: int
    inicio: datetime
    fin: datetime
    n_imagenes: int
    duracion_min: float
    completitud_pct: float
    dbz_max: float
    deriva_media_m: float | None
    deriva_max_m: float | None
    ids: list[int] = field(default_factory=list)


# ── Lectura ──────────────────────────────────────────────────────────────────
# Mismos valores que el servicio `db` de docker-compose.yml
DEFAULT_DB_URL = "postgresql://radar:radar@localhost:5432/radar_db"


def _leer_env_file(path: Path) -> dict[str, str]:
    vals: dict[str, str] = {}
    if path.exists():
        for linea in path.read_text().splitlines():
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                k, v = linea.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def _db_url_sync() -> str:
    raiz = Path(__file__).resolve().parents[1]
    url = (
        os.environ.get("DATABASE_URL")
        or _leer_env_file(raiz / ".env").get("DATABASE_URL")
        or DEFAULT_DB_URL
    )
    # asyncpg -> psycopg2 para correr sincrónico
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    # Si se corre fuera de Docker, el host 'db' no resuelve
    if "@db:" in url and not os.path.exists("/.dockerenv"):
        url = url.replace("@db:", "@localhost:")
    return url


def cargar_filas(desde: str | None, hasta: str | None):
    import psycopg2

    url = _db_url_sync()
    sql = """
        SELECT id, fecha_hora, geotiff_data, score_match
        FROM radar.imagenes_radar
        WHERE estado = 'completado' AND geotiff_data IS NOT NULL
    """
    params: list = []
    if desde:
        sql += " AND fecha_hora >= %s"
        params.append(desde)
    if hasta:
        sql += " AND fecha_hora < %s"
        params.append(hasta)
    sql += " ORDER BY fecha_hora"
    try:
        conn = psycopg2.connect(url)
    except psycopg2.OperationalError as exc:
        oculto = url.split("@")[-1]
        sys.exit(f"No pude conectar a la base ({oculto}).\n"
                 f"¿Está levantada? -> docker compose up db -d\n{exc}")
    with conn, conn.cursor(name="f0") as cur:
        cur.itersize = 50
        cur.execute(sql, params)
        for row in cur:
            yield row[0], row[1], bytes(row[2]), (float(row[3]) if row[3] is not None else None)


# ── Análisis (sin base: testeable) ───────────────────────────────────────────
def leer_geotiff(img_id, fecha, data: bytes, score) -> InfoImagen:
    with MemoryFile(data) as mf, mf.open() as ds:
        t = ds.transform
        arr = ds.read(1)
        crs = ds.crs.to_string() if ds.crs else "SIN_CRS"
        cx = t.c + t.a * ds.width / 2
        cy = t.f + t.e * ds.height / 2
        if ds.crs and ds.crs.to_epsg() == 3857:
            lat = math.degrees(2 * math.atan(math.exp(cy / _R_3857)) - math.pi / 2)
            k = math.cos(math.radians(lat))
        elif ds.crs and ds.crs.is_geographic:
            lat, k = cy, None
        else:
            lat, k = float("nan"), 1.0
        if k is None:  # grados -> metros
            pix_real = abs(t.a) * 111320 * math.cos(math.radians(lat))
        else:
            pix_real = abs(t.a) * k
        valid = arr[arr > NODATA_DBZ]
        return InfoImagen(
            id=img_id, fecha_hora=fecha, crs=crs, ancho=ds.width, alto=ds.height,
            pix_x=t.a, pix_y=t.e, origen_x=t.c, origen_y=t.f, lat_centro=lat,
            pix_real_m=pix_real,
            dbz_max=float(valid.max()) if valid.size else 0.0,
            pix_ge_umbral=int((arr >= UMBRAL_DBZ).sum()),
            score_match=score,
        )


def _dist_real_m(a: InfoImagen, b: InfoImagen) -> float:
    dx, dy = b.origen_x - a.origen_x, b.origen_y - a.origen_y
    if a.crs == "EPSG:3857":
        k = math.cos(math.radians(a.lat_centro))
        return math.hypot(dx, dy) * k
    if a.crs.startswith("EPSG:4326"):
        k = 111320.0
        return math.hypot(dx * k * math.cos(math.radians(a.lat_centro)), dy * k)
    return math.hypot(dx, dy)


def analizar(imgs: list[InfoImagen]):
    huecos = []
    for prev, cur in zip(imgs, imgs[1:]):
        cur.dt_min = (cur.fecha_hora - prev.fecha_hora).total_seconds() / 60
        if prev.crs == cur.crs:
            cur.deriva_m = _dist_real_m(prev, cur)
            cur.cambio_escala_pct = 100 * (cur.pix_x - prev.pix_x) / prev.pix_x
        if cur.dt_min > MAX_GAP_MIN:
            huecos.append({"desde": prev.fecha_hora, "hasta": cur.fecha_hora,
                           "minutos": round(cur.dt_min, 1)})

    dts = [i.dt_min for i in imgs if i.dt_min is not None]
    dt_med = median(dts) if dts else None

    # Eventos: rachas de imágenes con eco ≥ umbral y sin huecos grandes
    eventos: list[Evento] = []
    racha: list[InfoImagen] = []

    def cerrar():
        if len(racha) >= MIN_IMAGENES:
            dur = (racha[-1].fecha_hora - racha[0].fecha_hora).total_seconds() / 60
            esperadas = (dur / dt_med + 1) if dt_med else len(racha)
            der = [i.deriva_m for i in racha[1:] if i.deriva_m is not None]
            ev = Evento(
                n=len(eventos) + 1, inicio=racha[0].fecha_hora, fin=racha[-1].fecha_hora,
                n_imagenes=len(racha), duracion_min=round(dur, 1),
                completitud_pct=round(min(100.0, 100 * len(racha) / esperadas), 1),
                dbz_max=max(i.dbz_max for i in racha),
                deriva_media_m=round(sum(der) / len(der), 1) if der else None,
                deriva_max_m=round(max(der), 1) if der else None,
                ids=[i.id for i in racha],
            )
            for i in racha:
                i.evento = ev.n
            eventos.append(ev)
        racha.clear()

    for img in imgs:
        con_eco = img.pix_ge_umbral > 0
        if con_eco and racha and img.dt_min is not None and img.dt_min > MAX_GAP_MIN:
            cerrar()
        if con_eco:
            racha.append(img)
        else:
            cerrar()
    cerrar()
    return dt_med, huecos, eventos


# ── Salida ───────────────────────────────────────────────────────────────────
def _pct(vals, p):
    if not vals:
        return float("nan")
    return float(np.percentile(vals, p))


def escribir_csv(out: Path, imgs, huecos, eventos):
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "imagenes.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(imgs[0]).keys()))
        w.writeheader()
        for i in imgs:
            w.writerow(asdict(i))
    with open(out / "huecos.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["desde", "hasta", "minutos"])
        w.writeheader()
        w.writerows(huecos)
    with open(out / "eventos.csv", "w", newline="") as f:
        campos = [k for k in asdict(eventos[0]).keys()] if eventos else list(Evento.__dataclass_fields__)
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        for e in eventos:
            d = asdict(e)
            d["ids"] = " ".join(map(str, e.ids))
            w.writerow(d)


def resumen(imgs, dt_med, huecos, eventos, out: Path):
    crs = sorted({i.crs for i in imgs})
    pix = sorted({round(i.pix_x, 3) for i in imgs})
    pix_real = sorted({round(i.pix_real_m) for i in imgs})
    der = [i.deriva_m for i in imgs if i.deriva_m is not None]
    saltos_escala = sum(1 for i in imgs if i.cambio_escala_pct and abs(i.cambio_escala_pct) > 0.5)
    print("=" * 60)
    print(f"Imágenes completadas: {len(imgs)}")
    print(f"Rango: {imgs[0].fecha_hora}  →  {imgs[-1].fecha_hora}")
    print(f"CRS encontrados: {set(crs)}")
    print(f"Tamaño de píxel nominal (unid. CRS): {pix}")
    print(f"Tamaño de píxel real en el terreno: {pix_real} m")
    if saltos_escala:
        print(f"⚠ Cambios de escala entre consecutivas (>0.5 %): {saltos_escala}")
    print(f"Δt mediano: {dt_med:.1f} min | huecos > {MAX_GAP_MIN:.0f} min: {len(huecos)}"
          if dt_med else "Δt mediano: n/d")
    if der:
        print(f"Deriva geo entre consecutivas: mediana {median(der):.0f} m | "
              f"p95 {_pct(der, 95):.0f} m | máx {max(der):.0f} m")
    print(f"Eventos candidatos (≥{UMBRAL_DBZ:.0f} dBZ, ≥{MIN_IMAGENES} imágenes): {len(eventos)}")
    for e in eventos:
        print(f"  #{e.n}: {e.inicio} → {e.fin} | {e.n_imagenes} img | "
              f"{e.completitud_pct}% | {e.dbz_max:.0f} dBZ | deriva media {e.deriva_media_m} m")
    print(f"CSV en: {out.resolve()}")
    print("=" * 60)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desde", help="YYYY-MM-DD[ HH:MM]")
    ap.add_argument("--hasta", help="YYYY-MM-DD[ HH:MM] (exclusivo)")
    ap.add_argument("--salida", default="salidas_f0")
    args = ap.parse_args()

    imgs = []
    vistos: dict[str, InfoImagen] = {}
    duplicadas: list[tuple[int, datetime, int]] = []
    for img_id, fecha, data, score in cargar_filas(args.desde, args.hasta):
        h = hashlib.md5(data).hexdigest()
        if h in vistos:  # mismo contenido que una anterior: se ignora
            duplicadas.append((img_id, fecha, vistos[h].id))
            continue
        try:
            imgs.append(leer_geotiff(img_id, fecha, data, score))
            vistos[h] = imgs[-1]
        except Exception as exc:
            print(f"[warn] imagen {img_id} ({fecha}): no se pudo leer GeoTIFF: {exc}")
    if not imgs:
        sys.exit("No hay imágenes completadas con geotiff_data en ese rango. ¿Corriste el lote?")

    dt_med, huecos, eventos = analizar(imgs)
    out = Path(args.salida)
    escribir_csv(out, imgs, huecos, eventos)
    resumen(imgs, dt_med, huecos, eventos, out)
    if duplicadas:
        print(f"⚠ Ignoradas {len(duplicadas)} imágenes con GeoTIFF idéntico a una anterior:")
        for i, f, orig in duplicadas:
            print(f"    id {i} ({f:%Y-%m-%d %H:%M}) = id {orig}")
        print("  Para borrarlas: docker compose exec backend uv run --no-dev python -m src.scripts.limpiar_duplicados")


if __name__ == "__main__":
    main()
