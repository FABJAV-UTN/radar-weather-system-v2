"""
TESTS DE INTEGRACIÓN — API REST.

Testea los endpoints de FastAPI con TestClient, mockeando la DB.
Valida autenticación, permisos por rol, respuestas HTTP y schemas.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-para-tests-minimo-32-chars!!!")
os.environ.setdefault("TEMPLATE_DIR", "/tmp/templates")

from src.main import app
from src.auth.jwt import create_access_token, create_refresh_token
from src.auth.security import hash_password


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _token_headers(usuario_id: int, rol: str) -> dict:
    token = create_access_token(subject=usuario_id, role=rol)
    return {"Authorization": f"Bearer {token}"}


def _mock_usuario(id: int = 1, rol: str = "admin", activo: bool = True):
    u = MagicMock()
    u.id = id
    u.username = f"user_{id}"
    u.email = f"user{id}@test.com"
    u.password_hash = hash_password("password123")
    u.rol = MagicMock(value=rol)
    u.activo = activo
    u.ultimo_login = None
    u.created_at = MagicMock()
    u.model_dump = MagicMock(return_value={
        "id": id, "username": f"user_{id}", "email": f"user{id}@test.com",
        "rol": rol, "activo": activo, "ultimo_login": None, "created_at": "2026-01-01T00:00:00",
    })
    return u


# ─────────────────────────────────────────────────────────────────────────────
# TEST API: Health
# ─────────────────────────────────────────────────────────────────────────────

class TestAPIHealth:
    def test_health_check_sin_auth(self, client):
        """GET /health → 200 sin autenticación."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data


# ─────────────────────────────────────────────────────────────────────────────
# TEST API: Auth
# ─────────────────────────────────────────────────────────────────────────────

class TestAPIAuth:
    def test_login_credenciales_invalidas(self, client):
        """POST /auth/login con password incorrecto → 401."""
        usuario_mock = _mock_usuario(rol="operador")

        with (
            patch("src.api.routers.auth.UsuarioRepository") as MockRepo,
            patch("src.api.routers.auth.verify_password", return_value=False),
        ):
            inst = AsyncMock()
            inst.obtener_por_username = AsyncMock(return_value=usuario_mock)
            MockRepo.return_value = inst

            response = client.post("/api/v1/auth/login", json={
                "username": "user_1",
                "password": "wrong_password",
            })

        assert response.status_code == 401

    def test_login_usuario_inexistente(self, client):
        """POST /auth/login con usuario inexistente → 401."""
        with patch("src.api.routers.auth.UsuarioRepository") as MockRepo:
            inst = AsyncMock()
            inst.obtener_por_username = AsyncMock(return_value=None)
            MockRepo.return_value = inst

            response = client.post("/api/v1/auth/login", json={
                "username": "nadie",
                "password": "password123",
            })

        assert response.status_code == 401

    def test_login_exitoso_devuelve_tokens(self, client):
        """POST /auth/login exitoso → 200 con access_token y refresh_token."""
        usuario_mock = _mock_usuario(rol="admin")

        with (
            patch("src.api.routers.auth.UsuarioRepository") as MockRepo,
            patch("src.api.routers.auth.verify_password", return_value=True),
            patch("src.api.routers.auth.SesionRepository") as MockSesion,
        ):
            inst = AsyncMock()
            inst.obtener_por_username = AsyncMock(return_value=usuario_mock)
            inst.actualizar_ultimo_login = AsyncMock()
            MockRepo.return_value = inst

            sesion_inst = AsyncMock()
            sesion_inst.crear = AsyncMock()
            MockSesion.return_value = sesion_inst

            response = client.post("/api/v1/auth/login", json={
                "username": "user_1",
                "password": "password123",
            })

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_me_sin_token(self, client):
        """GET /auth/me sin Authorization → 403."""
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 403

    def test_me_con_token_valido(self, client):
        """GET /auth/me con token válido → 200 con datos de usuario."""
        headers = _token_headers(1, "admin")
        usuario_mock = _mock_usuario(1, "admin")

        with patch("src.api.routers.auth.UsuarioRepository") as MockRepo:
            inst = AsyncMock()
            inst.obtener_por_id = AsyncMock(return_value=usuario_mock)
            MockRepo.return_value = inst

            response = client.get("/api/v1/auth/me", headers=headers)

        assert response.status_code == 200

    def test_token_expirado_rechazado(self, client):
        """Endpoint protegido con token expirado → 401."""
        import jwt as pyjwt
        from datetime import datetime, timezone, timedelta
        from src.config import settings

        payload = {
            "sub": "1",
            "role": "admin",
            "type": "access",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),  # ya expiró
        }
        token = pyjwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
        headers = {"Authorization": f"Bearer {token}"}

        response = client.get("/api/v1/auth/me", headers=headers)
        assert response.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# TEST API: Imágenes
# ─────────────────────────────────────────────────────────────────────────────

class TestAPIImagenes:
    def test_listar_imagenes_sin_auth(self, client):
        """GET /imagenes sin token → 403."""
        response = client.get("/api/v1/imagenes")
        assert response.status_code == 403

    def test_listar_imagenes_con_auth(self, client):
        """GET /imagenes con token válido → 200 con estructura correcta."""
        headers = _token_headers(1, "visualizador")

        with patch("src.api.routers.imagenes.ImagenRadarRepository") as MockRepo:
            inst = AsyncMock()
            inst.listar = AsyncMock(return_value=[])
            MockRepo.return_value = inst

            response = client.get("/api/v1/imagenes", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data

    def test_obtener_imagen_no_encontrada(self, client):
        """GET /imagenes/999 → 404."""
        headers = _token_headers(1, "visualizador")

        with patch("src.api.routers.imagenes.ImagenRadarRepository") as MockRepo:
            inst = AsyncMock()
            inst.obtener_por_id = AsyncMock(return_value=None)
            MockRepo.return_value = inst

            response = client.get("/api/v1/imagenes/999", headers=headers)

        assert response.status_code == 404

    def test_descargar_geotiff_sin_datos(self, client):
        """GET /imagenes/1/geotiff → 404 si no hay GeoTIFF."""
        headers = _token_headers(1, "visualizador")

        imagen_mock = MagicMock()
        imagen_mock.geotiff_data = None

        with patch("src.api.routers.imagenes.ImagenRadarRepository") as MockRepo:
            inst = AsyncMock()
            inst.obtener_por_id = AsyncMock(return_value=imagen_mock)
            MockRepo.return_value = inst

            response = client.get("/api/v1/imagenes/1/geotiff", headers=headers)

        assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# TEST API: Procesamiento
# ─────────────────────────────────────────────────────────────────────────────

class TestAPIProcesamiento:
    def test_procesar_url_sin_auth(self, client):
        """POST /procesamiento/url sin token → 403."""
        response = client.post("/api/v1/procesamiento/url", json={})
        assert response.status_code == 403

    def test_procesar_url_duplicado_devuelve_409(self, client):
        """POST /procesamiento/url con imagen duplicada → 409 Conflict."""
        headers = _token_headers(1, "operador")

        with patch("src.api.routers.procesamiento.ejecutar_pipeline_url",
                   side_effect=ValueError("Imagen duplicada")):
            response = client.post("/api/v1/procesamiento/url", json={}, headers=headers)

        assert response.status_code == 409

    def test_procesar_local_archivo_no_existe(self, client):
        """POST /procesamiento/local con ruta inexistente → 404."""
        headers = _token_headers(1, "operador")

        response = client.post(
            "/api/v1/procesamiento/local",
            json={"file_path": "/tmp/no_existe_este_archivo.gif"},
            headers=headers,
        )
        assert response.status_code == 404

    def test_obtener_metricas_no_encontradas(self, client):
        """GET /procesamiento/99/metricas → 404."""
        headers = _token_headers(1, "visualizador")

        with patch("src.api.routers.procesamiento.MetricaProcesamientoRepository") as MockRepo:
            inst = AsyncMock()
            inst.obtener_por_imagen = AsyncMock(return_value=None)
            MockRepo.return_value = inst

            response = client.get("/api/v1/procesamiento/99/metricas", headers=headers)

        assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# TEST API: Admin — Roles
# ─────────────────────────────────────────────────────────────────────────────

class TestAPIAdminRoles:
    def test_listar_usuarios_como_visualizador_rechazado(self, client):
        """GET /admin/usuarios con rol visualizador → 403."""
        headers = _token_headers(3, "visualizador")
        response = client.get("/api/v1/admin/usuarios", headers=headers)
        assert response.status_code == 403

    def test_listar_usuarios_como_admin(self, client):
        """GET /admin/usuarios con rol admin → 200."""
        headers = _token_headers(1, "admin")

        with patch("src.api.routers.admin.UsuarioRepository") as MockRepo:
            inst = AsyncMock()
            inst.listar = AsyncMock(return_value=[])
            MockRepo.return_value = inst

            response = client.get("/api/v1/admin/usuarios", headers=headers)

        assert response.status_code == 200

    def test_crear_usuario_username_duplicado(self, client):
        """POST /admin/usuarios con username duplicado → 409."""
        headers = _token_headers(1, "admin")
        usuario_existente = _mock_usuario(2, "visualizador")

        with patch("src.api.routers.admin.UsuarioRepository") as MockRepo:
            inst = AsyncMock()
            inst.obtener_por_username = AsyncMock(return_value=usuario_existente)
            MockRepo.return_value = inst

            response = client.post(
                "/api/v1/admin/usuarios",
                json={
                    "username": "user_existente",
                    "email": "nuevo@test.com",
                    "password": "password123",
                    "rol": "visualizador",
                },
                headers=headers,
            )

        assert response.status_code == 409

    def test_crear_usuario_exitoso(self, client):
        """POST /admin/usuarios exitoso → 201 con datos del usuario."""
        headers = _token_headers(1, "admin")
        usuario_nuevo = _mock_usuario(5, "visualizador")

        with patch("src.api.routers.admin.UsuarioRepository") as MockRepo:
            inst = AsyncMock()
            inst.obtener_por_username = AsyncMock(return_value=None)
            inst.obtener_por_email = AsyncMock(return_value=None)
            inst.crear = AsyncMock(return_value=usuario_nuevo)
            MockRepo.return_value = inst

            response = client.post(
                "/api/v1/admin/usuarios",
                json={
                    "username": "nuevo_usuario",
                    "email": "nuevo@test.com",
                    "password": "password123",
                    "rol": "visualizador",
                },
                headers=headers,
            )

        assert response.status_code == 201

    def test_eliminar_propio_usuario_rechazado(self, client):
        """DELETE /admin/usuarios/1 cuando sos el usuario 1 → 400."""
        headers = _token_headers(1, "admin")  # usuario ID=1 intentando eliminarse
        response = client.delete("/api/v1/admin/usuarios/1", headers=headers)
        assert response.status_code == 400