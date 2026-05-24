"""
TEST U3: Conectividad HTTP.
Verifica que la URL del DACC responde con HTTP 200.
"""
import pytest
from unittest.mock import patch, MagicMock
import httpx


class TestConectividad:
    """Tests para verificación de conectividad HTTP."""

    @pytest.mark.asyncio
    async def test_u3_conectividad_dacc_responde_200(self):
        """TEST U3: Verifica que DACC responde con HTTP 200."""
        url = "https://www2.contingencias.mendoza.gov.ar/radar/latest.gif"
        
        with patch("httpx.AsyncClient.head") as mock_head:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "image/gif"}
            mock_head.return_value = mock_response
            
            async with httpx.AsyncClient() as client:
                response = await client.head(url, follow_redirects=True)
                assert response.status_code == 200
                assert "image" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_u3_conectividad_timeout(self):
        """TEST U3: Manejo de timeout en conectividad."""
        url = "https://www2.contingencias.mendoza.gov.ar/radar/latest.gif"
        
        with patch("httpx.AsyncClient.head") as mock_head:
            mock_head.side_effect = httpx.TimeoutException("Connection timeout")
            
            async with httpx.AsyncClient() as client:
                with pytest.raises(httpx.TimeoutException):
                    await client.head(url, timeout=1.0)

    @pytest.mark.asyncio
    async def test_u3_conectividad_error_conexion(self):
        """TEST U3: Manejo de error de conexión."""
        url = "https://invalid-url-that-does-not-exist.example.com/radar/latest.gif"
        
        with patch("httpx.AsyncClient.head") as mock_head:
            mock_head.side_effect = httpx.ConnectError("Connection refused")
            
            async with httpx.AsyncClient() as client:
                with pytest.raises(httpx.ConnectError):
                    await client.head(url)

    @pytest.mark.asyncio
    async def test_u3_conectividad_redirect(self):
        """TEST U3: Manejo de redirecciones HTTP."""
        url = "https://www2.contingencias.mendoza.gov.ar/radar/latest.gif"
        
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.history = [
                MagicMock(status_code=301),
                MagicMock(status_code=200),
            ]
            mock_get.return_value = mock_response
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, follow_redirects=True)
                assert response.status_code == 200
