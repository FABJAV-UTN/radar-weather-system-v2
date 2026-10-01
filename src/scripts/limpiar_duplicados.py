# src/scripts/limpiar_duplicados.py
"""
Borra imágenes con exactamente el mismo contenido (mismo MD5 de raw_data).

De cada grupo de duplicados se conserva la de fecha_hora más temprana (es la
hora en que ese escaneo ya existía) y se borran las demás, junto con sus
filas en metricas_procesamiento y procesamiento_pasos.

Por defecto NO borra nada: muestra lo que haría. Para borrar, --aplicar.

Uso (dentro del contenedor backend):

    docker compose exec backend uv run --no-dev python -m src.scripts.limpiar_duplicados
    docker compose exec backend uv run --no-dev python -m src.scripts.limpiar_duplicados --aplicar

Requiere la migración 8f3c1a2b9d47 (columna hash_raw): alembic upgrade head
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import text

from src.db.connection import AsyncSessionLocal

# Completa hash_raw por si quedó alguna fila sin calcular
_SQL_COMPLETAR = text("""
    UPDATE radar.imagenes_radar SET hash_raw = md5(raw_data)
    WHERE raw_data IS NOT NULL AND hash_raw IS NULL
""")

# Filas a borrar: todas menos la primera (por fecha_hora, luego id) de cada hash
_SQL_DUPLICADOS = text("""
    SELECT id, fecha_hora, hash_raw, conservar_id, conservar_fecha
    FROM (
        SELECT id, fecha_hora, hash_raw,
               row_number()  OVER w AS orden,
               first_value(id)         OVER w AS conservar_id,
               first_value(fecha_hora) OVER w AS conservar_fecha
        FROM radar.imagenes_radar
        WHERE hash_raw IS NOT NULL
        WINDOW w AS (PARTITION BY hash_raw ORDER BY fecha_hora, id)
    ) t
    WHERE orden > 1
    ORDER BY fecha_hora
""")


async def limpiar(aplicar: bool) -> int:
    async with AsyncSessionLocal() as session:
        await session.execute(_SQL_COMPLETAR)
        filas = (await session.execute(_SQL_DUPLICADOS)).all()

        for f in filas:
            print(f"  borrar id={f.id:<5} {f.fecha_hora:%Y-%m-%d %H:%M}  "
                  f"(igual a id={f.conservar_id} {f.conservar_fecha:%H:%M}, md5={f.hash_raw[:10]})")

        if aplicar and filas:
            ids = [f.id for f in filas]
            params = {"ids": ids}
            await session.execute(text("DELETE FROM radar.metricas_procesamiento WHERE imagen_id = ANY(:ids)"), params)
            await session.execute(text("DELETE FROM radar.procesamiento_pasos WHERE imagen_id = ANY(:ids)"), params)
            await session.execute(text("DELETE FROM radar.imagenes_radar WHERE id = ANY(:ids)"), params)
        await session.commit()
        return len(filas)


def main() -> None:
    ap = argparse.ArgumentParser(description="Borra imágenes con contenido duplicado (mismo MD5).")
    ap.add_argument("--aplicar", action="store_true", help="Borrar de verdad (sin esto, solo muestra).")
    args = ap.parse_args()

    n = asyncio.run(limpiar(args.aplicar))
    if n == 0:
        print("✓ No hay imágenes duplicadas.")
    elif args.aplicar:
        print(f"✓ Borradas {n} imágenes duplicadas (se conservó la primera de cada grupo).")
    else:
        print(f"→ {n} imágenes duplicadas. Nada borrado. Para borrar: --aplicar")


if __name__ == "__main__":
    main()
