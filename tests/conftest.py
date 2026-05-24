# tests/conftest.py
"""
Fixtures compartidos para toda la suite de tests.
"""
from __future__ import annotations

import io
import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.db.models import Base
from src.main import app
from src.api.dependencies import get_db

# ── DB de test (SQLite en memoria) ────────────────────────────────────────────
# Para tests que no necesitan PostGIS. Tests que sí lo necesiten usan la DB real.

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


def _imagen_radar_minima(ancho: int = 300, alto: int = 250) -> bytes:
    """Genera bytes GIF de una imagen de radar mínima válida."""
    arr = __import__("numpy").ones((alto, ancho, 3), dtype=__import__("numpy").uint8) * 80
    img = Image.fromarray(arr, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="GIF")
    buf.seek(0)
    return buf.read()


@pytest.fixture
def gif_bytes_radar() -> bytes:
    """Bytes de GIF de radar mínimo para usar en tests."""
    return _imagen_radar_minima()


@pytest.fixture
def imagen_pil_radar() -> Image.Image:
    """PIL Image de radar mínimo."""
    return Image.open(io.BytesIO(_imagen_radar_minima()))


# ── FastAPI TestClient ────────────────────────────────────────────────────────

@pytest.fixture
def api_url() -> str:
    return "http://testserver"


@pytest.fixture
def admin_token_headers() -> dict:
    """
    Headers con token de admin para tests de API.
    Genera un token real usando la función de JWT del proyecto.
    """
    from src.auth.jwt import create_access_token
    os.environ.setdefault("SECRET_KEY", "test-secret-key-para-tests-minimo-32-chars")
    token = create_access_token(subject=1, role="admin")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def operador_token_headers() -> dict:
    from src.auth.jwt import create_access_token
    os.environ.setdefault("SECRET_KEY", "test-secret-key-para-tests-minimo-32-chars")
    token = create_access_token(subject=2, role="operador")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def visualizador_token_headers() -> dict:
    from src.auth.jwt import create_access_token
    os.environ.setdefault("SECRET_KEY", "test-secret-key-para-tests-minimo-32-chars")
    token = create_access_token(subject=3, role="visualizador")
    return {"Authorization": f"Bearer {token}"}