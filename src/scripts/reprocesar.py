# src/scripts/reprocesar.py
"""
Reprocesa con el pipeline actual (fases 2-7) las imágenes de un rango de
fecha/hora, partiendo del GIF original guardado en raw_data.

Conserva id, fecha_hora y origen de cada imagen; reemplaza el GeoTIFF, las
imágenes intermedias y las métricas. Cada imagen va en su propia transacción:
si una falla, queda en estado 'error' y el resto sigue.

Por defecto NO modifica nada: muestra qué imágenes reprocesaría. Para
reprocesar, --aplicar.

Uso (dentro del contenedor backend, con el scheduler detenido):

    docker compose exec backend uv run --no-dev python -m src.scripts.reprocesar \\
        --desde "2026-10-13 00:00" --hasta "2026-10-13 23:59"
    docker compose exec backend uv run --no-dev python -m src.scripts.reprocesar \\
        --desde "2026-10-13 00:00" --hasta "2026-10-13 23:59" --aplicar

Las fechas son hora argentina, igual que fecha_hora en la base.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime

from src.db.connection import AsyncSessionLocal
from src.db.repository import ImagenRadarRepository
from src.subsistema1.orquestador import reprocesar_imagen

FORMATOS_FECHA = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def _fecha(texto: str) -> datetime:
    for formato in FORMATOS_FECHA:
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"Fecha inválida: '{texto}' (usar AAAA-MM-DD HH:MM)")


async def _listar(desde: datetime, hasta: datetime) -> list[tuple[int, datetime, str]]:
    async with AsyncSessionLocal() as session:
        return await ImagenRadarRepository(session).listar_ids_reprocesables(desde, hasta)


async def _reprocesar_una(imagen_id: int) -> tuple[bool, str]:
    async with AsyncSessionLocal() as session:
        try:
            resultado = await reprocesar_imagen(imagen_id, session)
            await session.commit()
        except Exception as exc:  # noqa: BLE001 — se informa y se sigue con la próxima
            await session.rollback()
            return False, f"{type(exc).__name__}: {exc}"
    if not resultado.exito:
        return False, resultado.mensaje_error or "error en el pipeline"
    geo = resultado.metricas.geo
    return True, f"geo={geo.estado_geo}" if geo is not None else "ok"


async def reprocesar(desde: datetime, hasta: datetime, aplicar: bool) -> tuple[int, int]:
    imagenes = await _listar(desde, hasta)
    print(f"{len(imagenes)} imágenes con raw_data entre {desde:%Y-%m-%d %H:%M} y {hasta:%Y-%m-%d %H:%M}")
    if not aplicar:
        for imagen_id, fecha_hora, estado in imagenes:
            print(f"  id={imagen_id:<6} {fecha_hora:%Y-%m-%d %H:%M:%S}  estado={estado}")
        return len(imagenes), 0

    fallidas = 0
    for n, (imagen_id, fecha_hora, _) in enumerate(imagenes, start=1):
        ok, detalle = await _reprocesar_una(imagen_id)
        fallidas += not ok
        marca = "✓" if ok else "✗"
        print(f"  [{n}/{len(imagenes)}] {marca} id={imagen_id:<6} {fecha_hora:%H:%M:%S}  {detalle}")
    return len(imagenes), fallidas


def main() -> None:
    ap = argparse.ArgumentParser(description="Reprocesa imágenes de un rango con el pipeline actual.")
    ap.add_argument("--desde", type=_fecha, required=True, help='"AAAA-MM-DD HH:MM" (hora argentina)')
    ap.add_argument("--hasta", type=_fecha, required=True, help='"AAAA-MM-DD HH:MM" (hora argentina)')
    ap.add_argument("--aplicar", action="store_true", help="Reprocesar de verdad (sin esto, solo lista).")
    args = ap.parse_args()
    if args.hasta < args.desde:
        ap.error("--hasta es anterior a --desde")

    # El detalle de cada fase va al log del pipeline; acá alcanza con el resumen.
    logging.basicConfig(level=logging.WARNING)

    total, fallidas = asyncio.run(reprocesar(args.desde, args.hasta, args.aplicar))
    if not args.aplicar:
        print("→ Nada modificado. Para reprocesar: --aplicar")
    elif fallidas:
        print(f"⚠ Reprocesadas {total - fallidas}/{total}; {fallidas} fallaron (quedan en estado 'error').")
    else:
        print(f"✓ Reprocesadas {total} imágenes.")


if __name__ == "__main__":
    main()
