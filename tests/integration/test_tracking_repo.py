"""
Tests de repositorios del tracking (F1) contra PostgreSQL + PostGIS real.

Usan una base APARTE (radar_test), nunca radar_db. La crean si no existe y
le aplican las migraciones con Alembic (así también se prueba la migración).
Si no hay Postgres disponible, se saltean.

    docker compose up db -d
    uv run pytest tests/integration/test_tracking_repo.py -v

Otra base: TEST_POSTGIS_URL=postgresql+asyncpg://usuario:clave@host:5432/base
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

TEST_URL = os.environ.get(
    "TEST_POSTGIS_URL", "postgresql+asyncpg://radar:radar@localhost:5432/radar_test"
)
RAIZ = Path(__file__).resolve().parents[2]
T0 = datetime(2025, 1, 6, 15, 12)


def _preparar_base() -> str | None:
    """Crea radar_test si hace falta y aplica las migraciones. Devuelve motivo si no se puede."""
    try:
        import psycopg2
        from alembic import command
        from alembic.config import Config
    except ImportError as exc:  # pragma: no cover
        return f"falta dependencia: {exc}"

    sync = TEST_URL.replace("postgresql+asyncpg://", "postgresql://")
    base = sync.rsplit("/", 1)[1]
    admin = sync.rsplit("/", 1)[0] + "/postgres"
    try:
        con = psycopg2.connect(admin, connect_timeout=3)
    except Exception as exc:
        return f"sin Postgres para tests ({exc.__class__.__name__})"
    con.autocommit = True
    with con.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (base,))
        if not cur.fetchone():
            cur.execute(f'CREATE DATABASE "{base}"')
    con.close()

    con = psycopg2.connect(sync)
    con.autocommit = True
    with con.cursor() as cur:  # partir siempre de cero
        cur.execute("DROP SCHEMA IF EXISTS radar CASCADE; DROP TABLE IF EXISTS public.alembic_version;")
    con.close()

    anterior = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_URL
    try:
        cfg = Config(str(RAIZ / "alembic.ini"))
        cfg.set_main_option("script_location", str(RAIZ / "alembic"))
        command.upgrade(cfg, "head")
    finally:
        if anterior is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = anterior
    return None


@pytest.fixture(scope="module")
def base_postgis():
    motivo = _preparar_base()
    if motivo:
        pytest.skip(motivo)
    return TEST_URL


@pytest_asyncio.fixture
async def s(base_postgis) -> AsyncSession:
    """Sesión dentro de una transacción que se deshace al final de cada test."""
    engine = create_async_engine(base_postgis, poolclass=NullPool)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False,
                               join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
    await engine.dispose()


# ── Ayudas ───────────────────────────────────────────────────────────────────

async def _imagenes(s: AsyncSession, n: int, t0: datetime = T0, paso_min: int = 4) -> list[int]:
    from src.db.models import ImagenRadar
    imgs = [ImagenRadar(fecha_hora=t0 + timedelta(minutes=paso_min * k), origen="local", estado="completado")
            for k in range(n)]
    s.add_all(imgs)
    await s.flush()
    return [i.id for i in imgs]


def _xy(lon: float, lat: float) -> tuple[float, float]:
    from rasterio.warp import transform
    xs, ys = transform("EPSG:4326", "EPSG:5344", [lon], [lat])
    return xs[0], ys[0]


def _celda(imagen_id, numero, fecha, lon, lat, dbz=50, area=19.6):
    from src.db.repository_tracking import CeldaNueva
    x, y = _xy(lon, lat)
    d = 2500  # cuadrado de 5 km de lado
    wkt = f"MULTIPOLYGON((({x-d} {y-d},{x+d} {y-d},{x+d} {y+d},{x-d} {y+d},{x-d} {y-d})))"
    return CeldaNueva(imagen_id=imagen_id, numero=numero, fecha_hora=fecha, x_m=x, y_m=y,
                      poligono_wkt=wkt, n_pixeles=45, area_km2=area, dbz_max=dbz, dbz_medio=dbz - 8)


async def _ejecucion(s, desde=T0, hasta=T0 + timedelta(hours=1)):
    from src.db.repository_tracking import EjecucionTrackingRepository
    return await EjecucionTrackingRepository(s).crear(
        "manual", {"D1": 35, "D5": 5344}, "test", rango_desde=desde, rango_hasta=hasta)


async def _track_de_5(s):
    """Track que avanza 0,03° lon y 0,01° lat cada 4 min (ejemplo del cap. 10)."""
    from src.db.repository_tracking import CeldaTormentaRepository, TrackTormentaRepository
    ej = await _ejecucion(s)
    img = await _imagenes(s, 5)
    celdas = [_celda(img[k], 1, T0 + timedelta(minutes=4 * k), -68.40 + 0.03 * k, -34.62 + 0.01 * k, 50 + k)
              for k in range(5)]
    crepo, trepo = CeldaTormentaRepository(s), TrackTormentaRepository(s)
    ids = await crepo.crear_varias(ej.id, celdas)
    tr = await trepo.crear(ej.id, T0)
    await crepo.asignar_track(ids, tr.id)
    await crepo.recalcular_cinematica(tr.id)
    await trepo.recalcular_totales(tr.id)
    return ej, tr, ids


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_migracion_crea_las_4_tablas(s):
    res = await s.execute(text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='radar' "
        "AND table_name IN ('ejecuciones_tracking','tracks_tormenta','celdas_tormenta','relaciones_celdas')"))
    assert len(res.all()) == 4


@pytest.mark.asyncio
async def test_cinematica_coincide_con_el_manual(s):
    from src.db.repository_tracking import CeldaTormentaRepository
    _, tr, _ = await _track_de_5(s)
    celdas = await CeldaTormentaRepository(s).de_track(tr.id)
    assert celdas[0].velocidad_kmh is None            # la primera no tiene paso previo
    for c in celdas[1:]:
        assert c.dt_min == pytest.approx(4.0)
        assert c.distancia_m == pytest.approx(2967, abs=2)
        assert c.velocidad_kmh == pytest.approx(44.5, abs=0.1)
        assert c.direccion_deg == pytest.approx(68, abs=1)


@pytest.mark.asyncio
async def test_columnas_generadas_devuelven_lon_lat(s):
    from src.db.repository_tracking import CeldaTormentaRepository
    _, tr, _ = await _track_de_5(s)
    c0 = (await CeldaTormentaRepository(s).de_track(tr.id))[0]
    await s.refresh(c0)
    assert c0.lon == pytest.approx(-68.40, abs=1e-6)
    assert c0.lat == pytest.approx(-34.62, abs=1e-6)
    assert c0.x_m > 2_000_000                          # falso este de la faja 2


@pytest.mark.asyncio
async def test_totales_del_track(s):
    from src.db.repository_tracking import TrackTormentaRepository
    _, tr, _ = await _track_de_5(s)
    t = await TrackTormentaRepository(s).obtener(tr.id)
    await s.refresh(t)
    assert t.n_celdas == 5
    assert t.duracion_min == pytest.approx(16)
    assert t.distancia_total_km == pytest.approx(11.87, abs=0.02)
    assert t.desplazamiento_neto_km == pytest.approx(11.87, abs=0.02)   # va en línea recta
    assert t.vel_media_kmh == pytest.approx(44.5, abs=0.1)
    assert t.direccion_media_deg == pytest.approx(68, abs=1)
    assert t.dbz_max == 54
    assert t.trayectoria is not None


@pytest.mark.asyncio
async def test_track_de_una_celda_no_tiene_trayectoria(s):
    from src.db.repository_tracking import CeldaTormentaRepository, TrackTormentaRepository
    ej = await _ejecucion(s)
    img = await _imagenes(s, 1)
    crepo, trepo = CeldaTormentaRepository(s), TrackTormentaRepository(s)
    ids = await crepo.crear_varias(ej.id, [_celda(img[0], 1, T0, -68.3, -34.6)])
    tr = await trepo.crear(ej.id, T0)
    await crepo.asignar_track(ids, tr.id)
    await crepo.recalcular_cinematica(tr.id)
    await trepo.recalcular_totales(tr.id)
    t = await trepo.obtener(tr.id)
    await s.refresh(t)
    assert t.n_celdas == 1 and t.trayectoria is None and t.distancia_total_km is None


@pytest.mark.asyncio
async def test_codigos_consecutivos_por_dia(s):
    from src.db.repository_tracking import TrackTormentaRepository
    ej = await _ejecucion(s)
    repo = TrackTormentaRepository(s)
    a = await repo.crear(ej.id, T0)
    b = await repo.crear(ej.id, T0 + timedelta(hours=1))
    c = await repo.crear(ej.id, T0 + timedelta(days=1))
    assert (a.codigo, b.codigo, c.codigo) == ("T-20250106-001", "T-20250106-002", "T-20250107-001")


@pytest.mark.asyncio
async def test_listar_por_rango_y_rango_vacio(s):
    from src.db.repository_tracking import TrackTormentaRepository
    _, tr, _ = await _track_de_5(s)
    repo = TrackTormentaRepository(s)
    dia = datetime(2025, 1, 6)
    items = await repo.listar(dia, dia + timedelta(days=1))
    assert [i["track"].id for i in items] == [tr.id]
    assert items[0]["trayectoria"]["type"] == "LineString"
    assert items[0]["trayectoria"]["coordinates"][0] == pytest.approx([-68.40, -34.62], abs=1e-4)
    # un día sin tormentas: lista vacía, no error
    otro = datetime(2025, 3, 1)
    assert await repo.listar(otro, otro + timedelta(days=1)) == []
    assert await repo.contar(otro, otro + timedelta(days=1)) == 0


@pytest.mark.asyncio
async def test_espurios_no_se_listan_por_defecto(s):
    from src.db.repository_tracking import TrackTormentaRepository
    _, tr, _ = await _track_de_5(s)
    repo = TrackTormentaRepository(s)
    await repo.cambiar_estado(tr.id, "espurio")
    dia = datetime(2025, 1, 6)
    assert await repo.contar(dia, dia + timedelta(days=1)) == 0
    assert await repo.contar(dia, dia + timedelta(days=1), estado="espurio") == 1


@pytest.mark.asyncio
async def test_relaciones_division_padres_e_hijos(s):
    from src.db.repository_tracking import RelacionCeldasRepository
    _, _, ids = await _track_de_5(s)
    repo = RelacionCeldasRepository(s)
    await repo.crear(ids[0], ids[1], "continuacion", "solapamiento", 0.6)
    await repo.crear(ids[0], ids[2], "division", "distancia", 0.4)
    hijos = await repo.hijos(ids[0])
    assert sorted(h.tipo for h in hijos) == ["continuacion", "division"]
    assert [p.celda_origen_id for p in await repo.padres(ids[2])] == [ids[0]]
    with pytest.raises(ValueError):
        await repo.crear(ids[1], ids[2], "cruce", "distancia", 0.5)


@pytest.mark.asyncio
async def test_la_base_rechaza_datos_invalidos(s):
    _, tr, ids = await _track_de_5(s)
    with pytest.raises(IntegrityError):
        async with s.begin_nested():
            await s.execute(text("UPDATE radar.celdas_tormenta SET dbz_max = 95 WHERE id = :i"), {"i": ids[0]})


@pytest.mark.asyncio
async def test_reproceso_borra_en_cascada(s):
    from src.db.models_tracking import CeldaTormenta, TrackTormenta
    from src.db.repository_tracking import EjecucionTrackingRepository
    await _track_de_5(s)
    n = await EjecucionTrackingRepository(s).borrar_las_que_solapan(T0, T0 + timedelta(minutes=30))
    assert n == 1
    assert (await s.execute(select(TrackTormenta))).first() is None
    assert (await s.execute(select(CeldaTormenta))).first() is None


@pytest.mark.asyncio
async def test_borrar_track_deja_celdas_sueltas(s):
    from src.db.models_tracking import CeldaTormenta
    _, tr, ids = await _track_de_5(s)
    await s.execute(text("DELETE FROM radar.tracks_tormenta WHERE id = :i"), {"i": tr.id})
    sueltas = (await s.execute(select(CeldaTormenta).where(CeldaTormenta.track_id.is_(None)))).scalars().all()
    assert len(sueltas) == 5


# ── API /tormentas ───────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def cliente(s):
    from httpx import ASGITransport, AsyncClient
    from src.api.dependencies import get_db
    from src.main import app

    async def _db():
        yield s
    app.dependency_overrides[get_db] = _db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_api_dia_sin_tormentas_devuelve_lista_vacia(cliente, admin_token_headers):
    r = await cliente.get("/api/v1/tormentas/tracks?desde=2025-03-01&hasta=2025-03-02", headers=admin_token_headers)
    assert r.status_code == 200
    assert r.json()["items"] == [] and r.json()["total"] == 0


@pytest.mark.asyncio
async def test_api_lista_y_detalle(cliente, s, admin_token_headers):
    _, tr, _ = await _track_de_5(s)
    r = await cliente.get("/api/v1/tormentas/tracks?desde=2025-01-06&hasta=2025-01-06", headers=admin_token_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1 and body["total_en_base"] == 1
    item = body["items"][0]
    assert item["codigo"] == "T-20250106-001"
    assert item["trayectoria"]["type"] == "LineString"
    r = await cliente.get(f"/api/v1/tormentas/tracks/{tr.id}", headers=admin_token_headers)
    assert r.status_code == 200
    det = r.json()
    assert len(det["celdas"]) == 5
    assert det["celdas"][1]["velocidad_kmh"] == pytest.approx(44.5, abs=0.1)
    assert det["celdas"][0]["poligono"]["type"] == "MultiPolygon"


@pytest.mark.asyncio
async def test_api_validaciones(cliente, admin_token_headers):
    h = admin_token_headers
    assert (await cliente.get("/api/v1/tormentas/tracks?desde=2025-01-07&hasta=2025-01-06", headers=h)).status_code == 422
    assert (await cliente.get("/api/v1/tormentas/tracks?desde=2025-01-01&hasta=2026-06-01", headers=h)).status_code == 422
    assert (await cliente.get("/api/v1/tormentas/tracks?desde=2025-01-06&hasta=2025-01-06&estado=x", headers=h)).status_code == 422
    assert (await cliente.get("/api/v1/tormentas/tracks/999999", headers=h)).status_code == 404
    assert (await cliente.get("/api/v1/tormentas/tracks?desde=2025-01-06&hasta=2025-01-06")).status_code in (401, 403)
