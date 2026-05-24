"""
TESTS E2E — Flujos completos del sistema.

Simula el uso real del sistema: login → token → operación → resultado.
Usa TestClient + mocks de DB y servicios externos.
"""
from __future__ import annotations

import io
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-para-tests-minimo-32-chars!!!")
os.environ.setdefault("TEMPLATE_DIR", "/tmp/templates")

from src.main import app
from src.auth.security import hash_password


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _mock_usuario_db(id: int = 1, rol: str = "admin", activo: bool = True):
    u = MagicMock()
    u.id = id
    u.username = "fabio"
    u.email = "fabio@dacc.gob.ar"
    u.password_hash = hash_password("admin1234")
    u.rol = MagicMock(value=rol)
    u.activo = activo
    u.ultimo_login = None
    u.created_at = datetime(2026, 1, 1)
    return u


class TestE2EFlujoAuth:
    """E2E: Flujo completo de autenticación."""

    def test_e2e_login_y_uso_de_token(self, client):
        """
        E2E: Usuario hace login → obtiene token → usa token en endpoint protegido.
        """
        usuario = _mock_usuario_db(1, "operador")

        # 1. Login
        with (
            patch("src.api.routers.auth.UsuarioRepository") as MockRepo,
            patch("src.api.routers.auth.verify_password", return_value=True),
            patch("src.api.routers.auth.SesionRepository") as MockSesion,
        ):
            inst = AsyncMock()
            inst.obtener_por_username = AsyncMock(return_value=usuario)
            inst.actualizar_ultimo_login = AsyncMock()
            MockRepo.return_value = inst

            sesion_inst = AsyncMock()
            sesion_inst.crear = AsyncMock()
            MockSesion.return_value = sesion_inst

            login_response = client.post("/api/v1/auth/login", json={
                "username": "fabio",
                "password": "admin1234",
            })

        assert login_response.status_code == 200
        tokens = login_response.json()
        access_token = tokens["access_token"]

        # 2. Usar token para listar imágenes
        headers = {"Authorization": f"Bearer {access_token}"}

        with patch("src.api.routers.imagenes.ImagenRadarRepository") as MockImg:
            inst = AsyncMock()
            inst.listar = AsyncMock(return_value=[])
            MockImg.return_value = inst

            list_response = client.get("/api/v1/imagenes", headers=headers)

        assert list_response.status_code == 200
        print("[E2E] Login → uso de token: ✓")

    def test_e2e_token_invalido_rechazado_en_todos_los_endpoints(self, client):
        """E2E: Token inválido devuelve 401 en cualquier endpoint protegido."""
        headers = {"Authorization": "Bearer token_falso_que_no_sirve"}
        endpoints = [
            ("GET", "/api/v1/imagenes"),
            ("GET", "/api/v1/admin/usuarios"),
            ("GET", "/api/v1/auth/me"),
        ]
        for metodo, url in endpoints:
            response = client.request(metodo, url, headers=headers)
            assert response.status_code == 401, f"Esperaba 401 en {metodo} {url}, obtuve {response.status_code}"
        print("[E2E] Token inválido rechazado en todos los endpoints ✓")


class TestE2EFlujoGestionUsuarios:
    """E2E: Admin crea un usuario, lo consulta y lo desactiva."""

    def test_e2e_admin_crea_y_desactiva_usuario(self, client):
        """E2E: Admin crea usuario nuevo y luego lo desactiva."""
        from src.auth.jwt import create_access_token
        admin_token = create_access_token(subject=1, role="admin")
        headers = {"Authorization": f"Bearer {admin_token}"}

        usuario_nuevo = MagicMock()
        usuario_nuevo.id = 10
        usuario_nuevo.username = "nuevo_op"
        usuario_nuevo.email = "op@test.com"
        usuario_nuevo.rol = MagicMock(value="operador")
        usuario_nuevo.activo = True
        usuario_nuevo.ultimo_login = None
        usuario_nuevo.created_at = datetime(2026, 5, 23)

        usuario_desactivado = MagicMock()
        usuario_desactivado.id = 10
        usuario_desactivado.username = "nuevo_op"
        usuario_desactivado.email = "op@test.com"
        usuario_desactivado.rol = MagicMock(value="operador")
        usuario_desactivado.activo = False
        usuario_desactivado.ultimo_login = None
        usuario_desactivado.created_at = datetime(2026, 5, 23)

        with patch("src.api.routers.admin.UsuarioRepository") as MockRepo:
            inst = AsyncMock()
            inst.obtener_por_username = AsyncMock(return_value=None)
            inst.obtener_por_email = AsyncMock(return_value=None)
            inst.crear = AsyncMock(return_value=usuario_nuevo)
            inst.obtener_por_id = AsyncMock(side_effect=[
                usuario_nuevo,       # primer obtener (para PATCH /estado)
                usuario_desactivado, # segundo obtener (para el return)
            ])
            inst.cambiar_estado = AsyncMock()
            MockRepo.return_value = inst

            # Crear usuario
            create_resp = client.post(
                "/api/v1/admin/usuarios",
                json={
                    "username": "nuevo_op",
                    "email": "op@test.com",
                    "password": "pass12345",
                    "rol": "operador",
                },
                headers=headers,
            )
            assert create_resp.status_code == 201

            # Desactivar
            deactivate_resp = client.patch(
                "/api/v1/admin/usuarios/10/estado",
                json={"activo": False},
                headers=headers,
            )
            assert deactivate_resp.status_code == 200

        print("[E2E] Crear + desactivar usuario ✓")


class TestE2EFlujoConsultaImagenes:
    """E2E: Operador consulta imágenes y descarga métricas."""

    def test_e2e_consulta_imagen_metricas_pasos(self, client):
        """E2E: Operador lista imágenes, obtiene detalle y consulta métricas."""
        from src.auth.jwt import create_access_token
        op_token = create_access_token(subject=2, role="operador")
        headers = {"Authorization": f"Bearer {op_token}"}

        # Mock de imagen
        imagen_mock = MagicMock()
        imagen_mock.id = 5
        imagen_mock.fecha_hora = datetime(2026, 5, 23, 14, 0, 0)
        imagen_mock.origen = "url"
        imagen_mock.estado = "completado"
        imagen_mock.tiene_marco = True
        imagen_mock.score_match = 0.88
        imagen_mock.crs = "EPSG:4326"
        imagen_mock.fecha_procesamiento = datetime(2026, 5, 23, 14, 5, 0)
        imagen_mock.created_at = datetime(2026, 5, 23, 14, 0, 0)
        imagen_mock.transform_affine = "| 0.01, 0, -70 |"
        imagen_mock.geotiff_data = b"FAKE_TIFF"

        metrica_mock = MagicMock()
        metrica_mock.pixeles_originales = 50000
        metrica_mock.pixeles_limpios = 45000
        metrica_mock.pixeles_rellenados = 3000
        metrica_mock.pixeles_perdidos = 2000
        metrica_mock.error_relleno_pct = 4.0
        metrica_mock.procesado_en = datetime(2026, 5, 23, 14, 5, 0)

        with (
            patch("src.api.routers.imagenes.ImagenRadarRepository") as MockImg,
            patch("src.api.routers.procesamiento.MetricaProcesamientoRepository") as MockMetrica,
            patch("src.api.routers.procesamiento.ProcesamentoPasoRepository") as MockPaso,
        ):
            img_inst = AsyncMock()
            img_inst.listar = AsyncMock(return_value=[imagen_mock])
            img_inst.obtener_por_id = AsyncMock(return_value=imagen_mock)
            MockImg.return_value = img_inst

            metrica_inst = AsyncMock()
            metrica_inst.obtener_por_imagen = AsyncMock(return_value=metrica_mock)
            MockMetrica.return_value = metrica_inst

            paso_inst = AsyncMock()
            paso_inst.listar_por_imagen = AsyncMock(return_value=[])
            MockPaso.return_value = paso_inst

            # Listar
            r1 = client.get("/api/v1/imagenes?estado=completado", headers=headers)
            assert r1.status_code == 200
            assert r1.json()["total"] == 1

            # Detalle
            r2 = client.get("/api/v1/imagenes/5", headers=headers)
            assert r2.status_code == 200
            assert r2.json()["score_match"] == 0.88

            # Métricas
            r3 = client.get("/api/v1/procesamiento/5/metricas", headers=headers)
            assert r3.status_code == 200
            assert r3.json()["pixeles_originales"] == 50000

            # Pasos
            r4 = client.get("/api/v1/procesamiento/5/pasos", headers=headers)
            assert r4.status_code == 200

        print("[E2E] Consulta imagen + métricas + pasos ✓")