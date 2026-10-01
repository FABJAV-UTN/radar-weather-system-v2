# src/scripts/demo_tracking.py
"""
Carga (o borra) tracks de DEMOSTRACIÓN para ver la página de Tracking
antes de que existan el detector y el tracker (F2–F3).

Usa imágenes reales ya cargadas (estado 'completado') de un día, pero las
celdas y trayectorias son SINTÉTICAS: tres tormentas que avanzan hacia el
NE/E a velocidades típicas, una de ellas se divide. Todo queda en una
ejecución con version_algoritmo = 'demo', así se identifica y se borra sin
tocar nada más.

Uso (dentro del contenedor backend):

    docker compose exec backend uv run --no-dev python -m src.scripts.demo_tracking            # día con más imágenes
    docker compose exec backend uv run --no-dev python -m src.scripts.demo_tracking --dia 2025-01-06
    docker compose exec backend uv run --no-dev python -m src.scripts.demo_tracking --borrar
"""
from __future__ import annotations

import argparse
import asyncio
import math
from datetime import date, datetime, time, timedelta

from rasterio.warp import transform
from sqlalchemy import delete, func, select

from src.db.connection import AsyncSessionLocal
from src.db.models import ImagenRadar
from src.db.models_tracking import EjecucionTracking
from src.db.repository_tracking import (
    CeldaNueva,
    CeldaTormentaRepository,
    EjecucionTrackingRepository,
    RelacionCeldasRepository,
    TrackTormentaRepository,
)

VERSION_DEMO = "demo"

# (lon0, lat0, velocidad km/h, rumbo hacia°, dbz_base, imagen inicial, n imágenes)
TORMENTAS = [
    (-68.75, -34.85, 38, 60, 52, 0, 14),
    (-68.45, -35.10, 45, 75, 58, 3, 18),
    (-69.00, -34.40, 30, 95, 47, 8, 10),
]


def _a_5344(lon: float, lat: float) -> tuple[float, float]:
    xs, ys = transform("EPSG:4326", "EPSG:5344", [lon], [lat])
    return xs[0], ys[0]


def _poligono(x: float, y: float, area_km2: float, rumbo: float) -> str:
    """Elipse de 16 lados alargada en la dirección de avance."""
    a = math.sqrt(area_km2 * 1e6 / math.pi * 1.8)
    b = area_km2 * 1e6 / (math.pi * a)
    th = math.radians(90 - rumbo)
    pts = []
    for k in range(16):
        t = 2 * math.pi * k / 16
        px, py = a * math.cos(t), b * math.sin(t)
        pts.append((x + px * math.cos(th) - py * math.sin(th), y + px * math.sin(th) + py * math.cos(th)))
    pts.append(pts[0])
    return "MULTIPOLYGON(((" + ",".join(f"{px:.1f} {py:.1f}" for px, py in pts) + ")))"


async def _dia_con_mas_imagenes(s) -> date | None:
    q = (select(func.date(ImagenRadar.fecha_hora).label("d"), func.count().label("n"))
         .where(ImagenRadar.estado == "completado")
         .group_by("d").order_by(func.count().desc()).limit(1))
    fila = (await s.execute(q)).first()
    return fila.d if fila else None


async def borrar(s) -> int:
    res = await s.execute(
        delete(EjecucionTracking).where(EjecucionTracking.version_algoritmo == VERSION_DEMO)
        .returning(EjecucionTracking.id))
    return len(res.all())


async def crear(dia: date | None) -> str:
    async with AsyncSessionLocal() as s:
        await borrar(s)
        dia = dia or await _dia_con_mas_imagenes(s)
        if dia is None:
            return "No hay imágenes completadas en la base: cargá un lote primero."
        t0 = datetime.combine(dia, time.min)
        imgs = list((await s.execute(
            select(ImagenRadar.id, ImagenRadar.fecha_hora)
            .where(ImagenRadar.estado == "completado",
                   ImagenRadar.fecha_hora >= t0, ImagenRadar.fecha_hora < t0 + timedelta(days=1))
            .order_by(ImagenRadar.fecha_hora))).all())
        if len(imgs) < 5:
            return f"El {dia} tiene {len(imgs)} imágenes completadas; hacen falta al menos 5."

        ej = await EjecucionTrackingRepository(s).crear(
            "manual", {"demo": True, "nota": "datos sintéticos para probar la interfaz"}, VERSION_DEMO,
            rango_desde=imgs[0].fecha_hora, rango_hasta=imgs[-1].fecha_hora + timedelta(minutes=1))
        crepo, trepo, rrepo = CeldaTormentaRepository(s), TrackTormentaRepository(s), RelacionCeldasRepository(s)
        n_tracks = n_celdas = 0
        for i, (lon0, lat0, v, rumbo, dbz0, k0, n) in enumerate(TORMENTAS):
            tramo = imgs[k0:k0 + n]
            if len(tramo) < 3:
                continue
            x0, y0 = _a_5344(lon0, lat0)
            celdas, numero = [], 10 + i
            for j, (img_id, fh) in enumerate(tramo):
                horas = (fh - tramo[0].fecha_hora).total_seconds() / 3600
                d = v * horas * 1000
                x = x0 + d * math.sin(math.radians(rumbo)) + 300 * math.sin(j * 1.7)
                y = y0 + d * math.cos(math.radians(rumbo)) + 300 * math.cos(j * 1.3)
                vida = math.sin(math.pi * (j + 1) / (len(tramo) + 1))     # crece y decae
                area = round(8 + 70 * vida, 1)
                dbz = int(min(70, dbz0 + 12 * vida))
                celdas.append(CeldaNueva(
                    imagen_id=img_id, numero=numero, fecha_hora=fh, x_m=x, y_m=y,
                    poligono_wkt=_poligono(x, y, area, rumbo), n_pixeles=int(area / 0.43) + 1,
                    area_km2=area, area_nucleo_km2=round(area * 0.3 * vida, 1),
                    dbz_max=dbz, dbz_medio=round(dbz - 9, 1)))
            ids = await crepo.crear_varias(ej.id, celdas)
            tr = await trepo.crear(ej.id, tramo[0].fecha_hora)
            await crepo.asignar_track(ids, tr.id)
            for a, b in zip(ids, ids[1:]):
                await rrepo.crear(a, b, "continuacion", "solapamiento", 0.6)
            await crepo.recalcular_cinematica(tr.id)
            await trepo.recalcular_totales(tr.id)
            await trepo.cambiar_estado(tr.id, "cerrado")
            n_tracks += 1
            n_celdas += len(ids)
        await EjecucionTrackingRepository(s).finalizar(
            ej.id, "ok", n_imagenes=len(imgs), n_celdas=n_celdas, n_tracks=n_tracks,
            mensaje="DEMO: datos sintéticos")
        await s.commit()
        return f"✓ Demo cargada para el {dia}: {n_tracks} tracks, {n_celdas} celdas (ejecución id={ej.id})."


async def solo_borrar() -> str:
    async with AsyncSessionLocal() as s:
        n = await borrar(s)
        await s.commit()
    return f"✓ Borradas {n} ejecuciones demo (con sus tracks y celdas)." if n else "No había datos demo."


def main() -> None:
    ap = argparse.ArgumentParser(description="Tracks de demostración para la página de Tracking.")
    ap.add_argument("--dia", type=date.fromisoformat, help="AAAA-MM-DD (por defecto, el día con más imágenes)")
    ap.add_argument("--borrar", action="store_true", help="Borrar los datos demo y salir")
    a = ap.parse_args()
    print(asyncio.run(solo_borrar() if a.borrar else crear(a.dia)))


if __name__ == "__main__":
    main()
