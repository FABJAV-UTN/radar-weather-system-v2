# src/scripts/limpiar_intentos.py
"""
Mantenimiento de la auditoría de descargas (radar.intentos_descarga).

Vacía la columna `archivo` (los GIF rechazados que se guardan para
diagnóstico) de los intentos con más de N días. La FILA de auditoría se
conserva: sigue quedando la fecha, si fue positivo o negativo y el motivo.
Solo se libera el espacio de los GIF.

Por defecto NO toca nada: muestra cuántos archivos y cuánto espacio liberaría.
Para aplicar, --aplicar.

Uso (dentro del contenedor backend):

    docker compose exec backend uv run --no-dev python -m src.scripts.limpiar_intentos
    docker compose exec backend uv run --no-dev python -m src.scripts.limpiar_intentos --dias 30 --aplicar

Antes de borrar, si querés mirarlos:
    uv run python scripts/exportar_rechazados.py --destino <carpeta>

Requiere la migración b7e2d4c91a05 (columna archivo): alembic upgrade head
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from src.db.connection import AsyncSessionLocal

_SQL_RESUMEN = text("""
    SELECT count(*) AS n, coalesce(sum(length(archivo)), 0) AS bytes,
           min(fecha_intento) AS desde, max(fecha_intento) AS hasta
    FROM radar.intentos_descarga
    WHERE archivo IS NOT NULL AND fecha_intento < :corte
""")

_SQL_VACIAR = text("""
    UPDATE radar.intentos_descarga SET archivo = NULL
    WHERE archivo IS NOT NULL AND fecha_intento < :corte
""")


async def limpiar(dias: int, aplicar: bool) -> int:
    corte = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=dias)
    async with AsyncSessionLocal() as session:
        fila = (await session.execute(_SQL_RESUMEN, {"corte": corte})).one()
        mb = fila.bytes / 1_048_576
        print(f"Intentos con GIF guardado anteriores a {corte:%Y-%m-%d %H:%M} UTC "
              f"({dias} días): {fila.n} archivos, {mb:.1f} MB"
              + (f" — del {fila.desde:%Y-%m-%d} al {fila.hasta:%Y-%m-%d}" if fila.n else ""))
        if not fila.n:
            return 0
        if not aplicar:
            print("No se tocó nada. Para vaciarlos: --aplicar")
            return 0
        await session.execute(_SQL_VACIAR, {"corte": corte})
        await session.commit()
        print(f"Listo: {fila.n} archivos vaciados. Las filas de auditoría se conservan.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dias", type=int, default=30, help="vaciar los GIF de intentos más viejos que esto (default 30)")
    ap.add_argument("--aplicar", action="store_true")
    args = ap.parse_args()
    return asyncio.run(limpiar(args.dias, args.aplicar))


if __name__ == "__main__":
    raise SystemExit(main())
