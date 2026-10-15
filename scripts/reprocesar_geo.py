"""
reprocesar_geo.py — Re-geolocaliza imágenes ya procesadas con el geolocalizar actual.

Para qué: las imágenes procesadas antes del 15/10/2026 tienen el GeoTIFF del
método legado (escala mal en todas; en la noche del 13/10, 45 frames corridos
~150 km y lluvia >= 35 dBZ borrada como si fuera clutter). Este script rehace
las fases 4 → 6 desde lo guardado en la base, igual que el pipeline:

    imagen recortada (cropped_data, o raw_data si no tenía marco)
      → clean_image  → dbz_map          (Fase 4, la del pipeline)
      → filled_data  (guardado)         (Fase 5)
      → geolocalizar(filled_rgb, dbz_map)  (Fase 6, versión robusta)

y actualiza en radar.imagenes_radar: geotiff_data, transform_affine, crs,
score_match, fecha_procesamiento; y en radar.metricas_procesamiento: dbz_max
(que también dependía de dónde se borraba el clutter). No toca raw/clean/
filled/cropped ni el estado.

Por defecto NO escribe nada (simulación). Con --aplicar escribe en la base.
Con --exportar DIR además deja los GeoTIFF nuevos en esa carpeta.

Uso (desde la raíz del repo, con la base levantada: docker compose up db -d):

    uv run python scripts/reprocesar_geo.py --desde-id 707 --hasta-id 895
    uv run python scripts/reprocesar_geo.py --desde-id 707 --hasta-id 895 --aplicar \\
        --exportar "$HOME/OneDrive/UNCUYO/PROYECTO CLIMA/radar_2026-10-13_reprocesado"

Antes de --aplicar conviene tener un respaldo:
    docker compose exec -T db pg_dump -U radar -Fc radar_db > ~/radar_db_antes_reproceso.dump
"""
from __future__ import annotations

import argparse
import collections
import io
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

# src.config exige estas variables; fuera de Docker los templates están en el repo.
os.environ.setdefault("TEMPLATE_DIR", str(RAIZ / "templates"))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://radar:radar@localhost:5432/radar_db")
os.environ.setdefault("SECRET_KEY", "solo-para-scripts-no-se-usa-aca-32-chars")

from src.subsistema1.crop import crop_imagen  # noqa: E402
from src.subsistema1.geolocalizar import geolocalizar  # noqa: E402
from src.subsistema1.limpiar import clean_image  # noqa: E402
from src.subsistema1.orquestador import _calcular_metricas  # noqa: E402
from src.subsistema1.rellenar import fill_gaps  # noqa: E402

DEFAULT_DB_URL = "postgresql://radar:radar@localhost:5432/radar_db"


# ── Conexión (mismo criterio que scripts/f0_inventario.py) ────────────────────

def _leer_env_file(path: Path) -> dict[str, str]:
    vals: dict[str, str] = {}
    if path.exists():
        for linea in path.read_text().splitlines():
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                k, v = linea.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def db_url_sync() -> str:
    url = (
        os.environ.get("REPROCESO_DB_URL")
        or _leer_env_file(RAIZ / ".env").get("DATABASE_URL")
        or DEFAULT_DB_URL
    )
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    if "@db:" in url and not os.path.exists("/.dockerenv"):
        url = url.replace("@db:", "@localhost:")
    return url


# ── Reproceso de una imagen (sin base: testeable) ─────────────────────────────

@dataclass
class Fila:
    id: int
    fecha_hora: datetime
    tiene_marco: bool
    raw_data: bytes | None
    cropped_data: bytes | None
    filled_data: bytes | None
    geotiff_data: bytes | None


@dataclass
class Resultado:
    id: int
    estado_geo: str
    corrimiento: tuple[float, float] | None
    geotiff: bytes
    transform_affine: str
    crs: str
    score: float
    dbz_max: float | None
    px35_antes: int | None   # píxeles >= 35 dBZ en el GeoTIFF viejo (grilla del GIF)
    px35_despues: int        # ídem con el clutter borrado donde corresponde (misma grilla)
    filled_recalculado: bool


def _abrir_png(b: bytes) -> np.ndarray:
    return np.array(Image.open(io.BytesIO(b)).convert("RGB"))


def imagen_recortada(fila: Fila) -> Image.Image:
    """La imagen que entró a la Fase 4 en el pipeline original."""
    if fila.tiene_marco:
        if fila.cropped_data:
            return Image.open(io.BytesIO(fila.cropped_data)).convert("RGB")
        if fila.raw_data:
            return Image.fromarray(crop_imagen(Image.open(io.BytesIO(fila.raw_data))).astype(np.uint8))
        raise ValueError("tiene_marco pero sin cropped_data ni raw_data")
    if fila.raw_data:
        img = Image.open(io.BytesIO(fila.raw_data))
        if getattr(img, "is_animated", False):
            img.seek(0)
        return img.convert("RGB")
    raise ValueError("sin raw_data")


def _px35(geotiff: bytes | None) -> int | None:
    if not geotiff:
        return None
    try:
        with rasterio.open(io.BytesIO(geotiff)) as src:
            return int(np.count_nonzero(src.read(1) >= 35))
    except Exception:
        return None


def reprocesar(fila: Fila) -> Resultado:
    clean_rgb, gap_mask, dbz_map = clean_image(imagen_recortada(fila))

    filled_rgb = _abrir_png(fila.filled_data) if fila.filled_data else None
    recalculado = False
    if filled_rgb is None or filled_rgb.shape[:2] != dbz_map.shape:
        filled_rgb = fill_gaps(clean_rgb, gap_mask)
        recalculado = True

    geo = geolocalizar(filled_rgb, dbz_map)
    stats = _calcular_metricas(clean_rgb, filled_rgb, dbz_map, clutter_mask=geo.clutter_mask)
    return Resultado(
        id=fila.id,
        estado_geo=geo.estado_geo,
        corrimiento=geo.corrimiento_px,
        geotiff=geo.geotiff_bytes,
        transform_affine=geo.transform_affine,
        crs=geo.crs_str,
        score=float(geo.score_match),
        dbz_max=stats["dbz_max"],
        px35_antes=_px35(fila.geotiff_data),
        # Se cuenta en la grilla del GIF (la del TIF viejo), no en la reproyectada,
        # para que antes/después sean comparables. En los frames donde el legado
        # borró lluvia, 'después' sube.
        px35_despues=int(np.count_nonzero((dbz_map >= 35) & ~geo.clutter_mask)),
        filled_recalculado=recalculado,
    )


# ── Base de datos ─────────────────────────────────────────────────────────────

SQL_FILAS = """
    SELECT id, fecha_hora, tiene_marco, raw_data, cropped_data, filled_data, geotiff_data
    FROM radar.imagenes_radar
    WHERE estado = 'completado' AND id BETWEEN %s AND %s
    ORDER BY id
"""

SQL_UPDATE_IMAGEN = """
    UPDATE radar.imagenes_radar
    SET geotiff_data = %s, transform_affine = %s, crs = %s, score_match = %s,
        fecha_procesamiento = %s, updated_at = %s
    WHERE id = %s
"""

SQL_UPDATE_METRICA = """
    UPDATE radar.metricas_procesamiento SET dbz_max = %s WHERE imagen_id = %s
"""


def _nombre_tif(fila: Fila) -> str:
    return f"radar_{fila.id}_{fila.fecha_hora:%Y%m%d_%H%M%S}.tif"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desde-id", type=int, required=True)
    ap.add_argument("--hasta-id", type=int, required=True)
    ap.add_argument("--aplicar", action="store_true", help="escribir en la base (sin esto, solo simula)")
    ap.add_argument("--exportar", type=Path, help="carpeta donde dejar los GeoTIFF nuevos")
    args = ap.parse_args(argv)

    import psycopg2

    url = db_url_sync()
    try:
        conn = psycopg2.connect(url)
    except psycopg2.OperationalError as exc:
        sys.exit(f"No pude conectar a la base ({url.split('@')[-1]}).\n"
                 f"¿Está levantada? -> docker compose up db -d\n{exc}")

    if args.exportar:
        args.exportar.mkdir(parents=True, exist_ok=True)

    with conn.cursor() as cur:
        cur.execute(SQL_FILAS, (args.desde_id, args.hasta_id))
        filas = [Fila(*[bytes(v) if isinstance(v, memoryview) else v for v in r]) for r in cur.fetchall()]
    if not filas:
        sys.exit(f"No hay imágenes 'completado' con id entre {args.desde_id} y {args.hasta_id}.")

    print(f"{'SIMULACIÓN' if not args.aplicar else 'APLICANDO'}: {len(filas)} imágenes "
          f"(id {filas[0].id}–{filas[-1].id})\n")
    print(f"{'id':>5}  {'fecha_hora':19}  {'estado_geo':24} {'corrim.':>10}  {'≥35 antes':>9} {'≥35 ahora':>9}  dbz_max")

    estados: collections.Counter[str] = collections.Counter()
    errores: list[tuple[int, str]] = []
    ahora = datetime.now(UTC).replace(tzinfo=None)
    for fila in filas:
        try:
            r = reprocesar(fila)
        except Exception as exc:  # una imagen rota no frena el lote
            errores.append((fila.id, repr(exc)))
            print(f"{fila.id:>5}  ERROR: {exc}")
            continue
        estados[r.estado_geo] += 1
        corr = "" if r.corrimiento is None else f"{r.corrimiento[0]:+.0f},{r.corrimiento[1]:+.0f}"
        antes = "-" if r.px35_antes is None else str(r.px35_antes)
        print(f"{r.id:>5}  {fila.fecha_hora:%Y-%m-%d %H:%M:%S}  {r.estado_geo:24} {corr:>10}  "
              f"{antes:>9} {r.px35_despues:>9}  {r.dbz_max}"
              + ("  (filled recalculado)" if r.filled_recalculado else ""))

        if args.exportar:
            (args.exportar / _nombre_tif(fila)).write_bytes(r.geotiff)
        if args.aplicar:
            with conn.cursor() as cur:
                cur.execute(SQL_UPDATE_IMAGEN, (psycopg2.Binary(r.geotiff), r.transform_affine, r.crs,
                                                round(r.score, 4), ahora, ahora, r.id))
                cur.execute(SQL_UPDATE_METRICA, (r.dbz_max, r.id))
            conn.commit()

    conn.close()
    print("\nResumen de estados:", dict(estados))
    if errores:
        print(f"Errores ({len(errores)}):", errores)
    if not args.aplicar:
        print("\nNo se escribió nada en la base. Para aplicar, repetí con --aplicar.")
    if args.exportar:
        print(f"GeoTIFF nuevos en: {args.exportar}")
    return 1 if errores else 0


if __name__ == "__main__":
    raise SystemExit(main())
