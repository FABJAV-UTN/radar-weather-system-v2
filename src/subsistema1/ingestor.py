# src/subsistema1/ingestor.py
"""
Fase 1 del pipeline: Adquisición de datos.

Dos rutas de ingesta:
- Ruta A (local): Lee archivo PNG/GIF de disco, extrae timestamp del nombre del archivo.
  El nombre del archivo ya contiene hora local (sin UTC offset) → no se aplica conversión.
- Ruta B (URL DACC): Descarga latest.gif, extrae timestamp via OCR.
  El timestamp del marco está en UTC → OCR aplica offset UTC-3.

Sin persistencia directa: devuelve los bytes crudos y el timestamp al orquestador,
que decide si hay duplicado antes de crear el registro en base de datos.
"""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from PIL import Image

from src.config import settings
from src.subsistema1.ocr import extract_timestamp

logger = logging.getLogger(__name__)

# Patrón de nombre de archivo: radar_YYYYMMDD_HHMMSS.gif
# Ej: radar_20260130_1514_55.gif o radar_20260523_143000.gif
_FILENAME_PATTERN = re.compile(
    r"(?:radar_)?(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(?:_(\d{2}))?"
)


class IngestaResultado:
    """Resultado de la ingesta: bytes crudos + metadatos."""

    __slots__ = ("raw_bytes", "fecha_hora", "origen", "imagen_pil")

    def __init__(
        self,
        raw_bytes: bytes,
        fecha_hora: datetime,
        origen: str,
        imagen_pil: Image.Image,
    ) -> None:
        self.raw_bytes = raw_bytes
        self.fecha_hora = fecha_hora
        self.origen = origen
        self.imagen_pil = imagen_pil


def _apply_timezone_offset(dt: datetime) -> datetime:
    """Aplica el offset UTC→Mendoza (UTC-3). Solo se usa para timestamps UTC (OCR)."""
    return dt + timedelta(hours=settings.radar_timezone_offset_hours)


def _extraer_timestamp_de_nombre(filename: str) -> datetime | None:
    """
    Extrae fecha/hora del nombre de archivo.

    Formato esperado: radar_YYYYMMDD_HHMMSS.gif
    También acepta: radar_YYYYMMDD_HHMM_SS.gif

    El nombre de archivo ya contiene hora local (UTC-3). No se aplica ningún
    offset: el dato se devuelve tal cual está en el nombre.

    Args:
        filename: Nombre del archivo (sin ruta).

    Returns:
        datetime en hora local (tal como figura en el nombre), o None si no
        coincide el patrón.
    """
    m = _FILENAME_PATTERN.search(filename)
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6)) if m.group(6) else 0
    try:
        # Sin offset: el nombre del archivo ya está en hora local
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


async def ingestar_local(file_path: Path) -> IngestaResultado:
    """
    Ruta A: Lee un archivo de imagen local y extrae timestamp del nombre.

    El timestamp del nombre de archivo se asume en hora local (sin offset UTC).
    Si la imagen tiene marco, el orquestador reemplazará este timestamp con el
    resultado del OCR (que sí aplica el offset UTC-3).

    Args:
        file_path: Ruta absoluta al archivo PNG o GIF.

    Returns:
        IngestaResultado con raw_bytes, fecha_hora (hora local del nombre) y origen='local'.

    Raises:
        FileNotFoundError: Si el archivo no existe.
        ValueError: Si no se puede extraer el timestamp del nombre.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Archivo no encontrado: {file_path}")

    raw_bytes = file_path.read_bytes()
    imagen = Image.open(io.BytesIO(raw_bytes))

    # Extraer timestamp del nombre del archivo (hora local, sin offset)
    fecha_hora = _extraer_timestamp_de_nombre(file_path.name)
    if fecha_hora is None:
        raise ValueError(
            f"No se pudo extraer timestamp del nombre '{file_path.name}'. "
            f"Formato esperado: radar_YYYYMMDD_HHMMSS.gif"
        )

    logger.info("Ingestado local: %s → %s (hora local, sin offset)", file_path.name, fecha_hora)
    return IngestaResultado(
        raw_bytes=raw_bytes,
        fecha_hora=fecha_hora,
        origen="local",
        imagen_pil=imagen,
    )


async def ingestar_url(url: str | None = None) -> IngestaResultado:
    """
    Ruta B: Descarga latest.gif desde la URL del DACC y extrae timestamp via OCR.

    Las imágenes del DACC siempre tienen marco con timestamp en UTC.
    El OCR aplica el offset UTC-3 internamente.

    Args:
        url: URL de descarga. Si None, usa settings.radar_url.

    Returns:
        IngestaResultado con raw_bytes, fecha_hora (UTC-3) y origen='url'.

    Raises:
        httpx.HTTPError: Si falla la descarga.
        ValueError: Si el OCR no puede extraer un timestamp válido.
    """
    target_url = url or settings.radar_url

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        logger.info("Descargando desde: %s", target_url)
        response = await client.get(target_url)
        response.raise_for_status()
        raw_bytes = response.content

    imagen = Image.open(io.BytesIO(raw_bytes))

    # Extraer timestamp via OCR (aplica offset UTC-3 internamente)
    fecha_hora = extract_timestamp(imagen)
    if fecha_hora is None:
        raise ValueError(
            f"OCR no pudo extraer timestamp válido desde {target_url}"
        )

    logger.info("Ingestado URL: %s → %s", target_url, fecha_hora)
    return IngestaResultado(
        raw_bytes=raw_bytes,
        fecha_hora=fecha_hora,
        origen="url",
        imagen_pil=imagen,
    )