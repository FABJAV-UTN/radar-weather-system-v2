"""
exportar_rechazados.py — Exporta los GIF de los intentos de descarga RECHAZADOS.

Desde el 15/10/2026, cuando un intento se rechaza porque el GIF llegó
incompleto o porque no se pudo leer la hora (OCR), los bytes descargados se
guardan en radar.intentos_descarga.archivo. Este script los deja en una
carpeta para mirarlos:

    rechazado_<id>_<AAAAMMDD>_<HHMMSS>UTC_<categoria>.gif

Uso (desde la raíz del repo, con la base levantada):

    uv run python scripts/exportar_rechazados.py --destino ~/rechazados
    uv run python scripts/exportar_rechazados.py --destino ~/rechazados --desde "2026-10-16 00:00" --hasta "2026-10-16 12:00"

--desde / --hasta van en UTC, igual que fecha_intento.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from exportar_originales import extension  # noqa: E402
from reprocesar_geo import db_url_sync  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--destino", type=Path, required=True)
    ap.add_argument("--desde", help="fecha_intento mínima (UTC), ej. '2026-10-16 00:00'")
    ap.add_argument("--hasta", help="fecha_intento máxima (UTC)")
    args = ap.parse_args(argv)

    import psycopg2

    url = db_url_sync()
    try:
        conn = psycopg2.connect(url)
    except psycopg2.OperationalError as exc:
        sys.exit(f"No pude conectar a la base ({url.split('@')[-1]}).\n"
                 f"¿Está levantada? -> docker compose up db -d\n{exc}")

    sql = ("SELECT id, fecha_intento, motivo_fallo, archivo FROM radar.intentos_descarga "
           "WHERE archivo IS NOT NULL")
    params: list = []
    if args.desde:
        sql += " AND fecha_intento >= %s"
        params.append(args.desde)
    if args.hasta:
        sql += " AND fecha_intento < %s"
        params.append(args.hasta)
    sql += " ORDER BY fecha_intento"

    args.destino.mkdir(parents=True, exist_ok=True)
    n = 0
    with conn, conn.cursor() as cur:
        cur.execute(sql, params)
        for id_, fecha, motivo, archivo in cur:
            datos = bytes(archivo)
            categoria = re.sub(r"\W+", "_", (motivo or "sin_motivo").split(":", 1)[0]).strip("_")
            nombre = f"rechazado_{id_}_{fecha:%Y%m%d_%H%M%S}UTC_{categoria}{extension(datos)}"
            (args.destino / nombre).write_bytes(datos)
            n += 1
    conn.close()
    print(f"Exportados {n} archivos rechazados a {args.destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
