"""
exportar_originales.py — Exporta los archivos ORIGINALES (raw_data) de la base.

raw_data es el archivo tal cual entró al pipeline (el GIF del DACC que bajó el
scheduler, o el PNG/GIF cargado a mano). Se guardan con el mismo nombre que los
GeoTIFF de reprocesar_geo.py, para poder ponerlos lado a lado:

    radar_<id>_<AAAAMMDD>_<HHMMSS>.gif   (o .png, según el contenido)

Uso (desde la raíz del repo, con la base levantada):

    uv run python scripts/exportar_originales.py --desde-id 707 --hasta-id 895 --destino "$HOME/OneDrive/UNCUYO/PROYECTO CLIMA/radar_2026-10-13_gif_originales"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reprocesar_geo import db_url_sync  # noqa: E402  (misma conexión que el reproceso)


def extension(datos: bytes) -> str:
    """Extensión según los primeros bytes del archivo (no confiar en el nombre)."""
    if datos[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if datos[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if datos[:3] == b"\xff\xd8\xff":
        return ".jpg"
    return ".bin"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desde-id", type=int, required=True)
    ap.add_argument("--hasta-id", type=int, required=True)
    ap.add_argument("--destino", type=Path, required=True)
    args = ap.parse_args(argv)

    import psycopg2

    url = db_url_sync()
    try:
        conn = psycopg2.connect(url)
    except psycopg2.OperationalError as exc:
        sys.exit(f"No pude conectar a la base ({url.split('@')[-1]}).\n"
                 f"¿Está levantada? -> docker compose up db -d\n{exc}")

    args.destino.mkdir(parents=True, exist_ok=True)
    n = sin_raw = 0
    with conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, fecha_hora, raw_data FROM radar.imagenes_radar "
            "WHERE id BETWEEN %s AND %s ORDER BY id",
            (args.desde_id, args.hasta_id),
        )
        for id_, fecha, raw in cur:
            if raw is None:
                sin_raw += 1
                print(f"{id_}: sin raw_data, salteada")
                continue
            datos = bytes(raw)
            nombre = f"radar_{id_}_{fecha:%Y%m%d_%H%M%S}{extension(datos)}"
            (args.destino / nombre).write_bytes(datos)
            n += 1
    conn.close()
    print(f"Exportados {n} archivos a {args.destino}" + (f" ({sin_raw} sin raw_data)" if sin_raw else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
