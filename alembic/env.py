# alembic/env.py
"""
Configuración de Alembic para migraciones sync con PostGIS.
Apunta a src/db/models.py para autogenerar migraciones desde los modelos ORM.
"""
import os
from logging.config import fileConfig

from sqlalchemy import create_engine, pool, text

from alembic import context

# ── Importar modelos para autogenerate ───────────────────────────────────────
from src.db.models import Base  # noqa: F401 — necesario para autogenerate

# ── Config de Alembic ─────────────────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

database_url = os.environ.get("DATABASE_URL")
if database_url:
    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    config.set_main_option("sqlalchemy.url", sync_url)


# ── Filtro: solo schema 'radar' ───────────────────────────────────────────────

def _include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table":
        return getattr(obj, "schema", None) == "radar"
    if type_ == "index":
        return getattr(obj.table, "schema", None) == "radar"
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_object=_include_object,
        version_table_schema="public",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url")
    engine = create_engine(url, poolclass=pool.NullPool)

    with engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS radar"))
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=_include_object,
            version_table_schema="public",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()