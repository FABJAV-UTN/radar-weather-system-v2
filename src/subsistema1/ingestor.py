# src/subsistema1/ingestor.py
"""
Fase 1 del pipeline: Adquisición de datos.

Dos rutas de ingesta:
- Ruta A (local): Lee archivo PNG/GIF de disco, extrae timestamp del nombre del archivo.
  El nombre del archivo ya contiene hora local (sin UTC offset) → no se aplica conversión.
- Ruta B (URL DACC): Descarga la imagen; el orquestador resuelve el timestamp
  (marco → OCR UTC-3, o nombre en la URL si no hay marco).

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
logger = logging.getLogger(__name__)

_YEAR_MIN = 1990
_YEAR_MAX = 2100
_UBICACION_DEFAULT = "mendoza"
_PREFIJO_UBICACION_RE = re.compile(r"^([a-zA-Z]+)")


class IngestaResultado:
    """Resultado de la ingesta: bytes crudos + metadatos."""

    __slots__ = ("raw_bytes", "fecha_hora", "origen", "imagen_pil")

    def __init__(
        self,
        raw_bytes: bytes,
        fecha_hora: datetime | None,
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


def _es_anio(valor: int) -> bool:
    return _YEAR_MIN <= valor <= _YEAR_MAX


def _ubicacion_desde_nombre(stem: str) -> str:
    """
    Prefijo alfabético del archivo (lugar). Si el nombre empieza con dígitos,
    no incluye lugar → Mendoza por defecto.
    """
    match = _PREFIJO_UBICACION_RE.match(stem)
    if match:
        return match.group(1).lower().rstrip("_")
    return _UBICACION_DEFAULT


def _parsear_hora_desde_partes(partes: list[str], desde: int) -> tuple[int, int, int] | None:
    """Interpreta HHMM, HHMMSS o HH + MM + SS en partes[desde:]."""
    if desde >= len(partes):
        return 0, 0, 0

    token = partes[desde]
    if len(token) == 6 and token.isdigit():
        return int(token[0:2]), int(token[2:4]), int(token[4:6])
    if len(token) == 4 and token.isdigit():
        if (
            desde + 1 < len(partes)
            and len(partes[desde + 1]) <= 2
            and partes[desde + 1].isdigit()
        ):
            return int(token[0:2]), int(token[2:4]), int(partes[desde + 1])
        return int(token[0:2]), int(token[2:4]), 0
    return None


def _fecha_desde_bloque_ocho(token: str) -> tuple[int, int, int] | None:
    if len(token) != 8 or not token.isdigit():
        return None
    year, month, day = int(token[0:4]), int(token[4:6]), int(token[6:8])
    if not _es_anio(year) or not (1 <= month <= 12) or not (1 <= day <= 31):
        return None
    return year, month, day


def _fecha_desde_partes(partes: list[str], indice_anio: int) -> tuple[int, int, int, int] | None:
    """
    A partir de un grupo de 4 dígitos = año, resuelve mes/día.

    - Año al inicio del trío: YYYY, MM, DD
    - Año al final del trío: DD, MM, YYYY

    Returns:
        (year, month, day, indice_siguiente_hora) o None.
    """
    year = int(partes[indice_anio])
    if not _es_anio(year):
        return None

    # YYYY-MM-DD (o YYYY-M-D por grupos separados)
    if indice_anio + 2 < len(partes):
        month, day = int(partes[indice_anio + 1]), int(partes[indice_anio + 2])
        if 1 <= month <= 12 and 1 <= day <= 31:
            return year, month, day, indice_anio + 3

    # DD-MM-YYYY
    if indice_anio >= 2:
        day, month = int(partes[indice_anio - 2]), int(partes[indice_anio - 1])
        if 1 <= month <= 12 and 1 <= day <= 31:
            return year, month, day, indice_anio + 1

    return None


def _extraer_timestamp_de_nombre(filename: str) -> datetime | None:
    """
    Extrae fecha/hora del nombre de archivo.

    Busca secuencias numéricas: un bloque de 4 dígitos es el año; los siguientes
  (o anteriores) son mes y día. Soporta:

    - ``radar_20260523_143000.gif`` (YYYYMMDD + HHMMSS)
    - ``2020-09-05_0000.gif`` (YYYY-MM-DD + HHMM)
    - ``05-09-2020_0000.gif`` (DD-MM-YYYY + HHMM)
    - Sin prefijo de lugar → se asume ubicación ``mendoza``

    La hora del nombre es hora local; no se aplica offset UTC.

    Args:
        filename: Nombre del archivo (sin ruta).

    Returns:
        datetime en hora local, o None si no hay fecha válida.
    """
    stem = Path(filename).stem
    partes = re.findall(r"\d+", stem)
    if not partes:
        return None

    candidatos: list[tuple[int, int, int, int]] = []

    for i, token in enumerate(partes):
        bloque = _fecha_desde_bloque_ocho(token)
        if bloque:
            year, month, day = bloque
            candidatos.append((year, month, day, i + 1))
            continue
        if len(token) == 4 and token.isdigit() and _es_anio(int(token)):
            parsed = _fecha_desde_partes(partes, i)
            if parsed:
                candidatos.append(parsed)

    for year, month, day, hora_desde in candidatos:
        hora = _parsear_hora_desde_partes(partes, hora_desde)
        if hora is None:
            continue
        hour, minute, second = hora
        try:
            return datetime(year, month, day, hour, minute, second)
        except ValueError:
            continue

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
            f"Se esperan grupos numéricos con año (4 dígitos), mes, día y hora."
        )

    ubicacion = _ubicacion_desde_nombre(file_path.stem)
    logger.info(
        "Ingestado local [%s]: %s → %s (hora local, sin offset)",
        ubicacion,
        file_path.name,
        fecha_hora,
    )
    return IngestaResultado(
        raw_bytes=raw_bytes,
        fecha_hora=fecha_hora,
        origen="local",
        imagen_pil=imagen,
    )


async def ingestar_url(url: str | None = None) -> IngestaResultado:
    """
    Ruta B: Descarga la imagen desde la URL del DACC.

    El timestamp definitivo lo resuelve el orquestador (marco → OCR UTC-3;
    sin marco → nombre del archivo en la URL, si aplica).

    Args:
        url: URL de descarga. Si None, usa settings.radar_url.

    Returns:
        IngestaResultado con raw_bytes y origen='url'. ``fecha_hora`` puede ser
        None si el nombre en la URL no trae fecha (ej. latest.gif).

    Raises:
        httpx.HTTPError: Si falla la descarga.
    """
    from urllib.parse import urlparse

    target_url = url or settings.radar_url

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        logger.info("Descargando desde: %s", target_url)
        response = await client.get(target_url)
        response.raise_for_status()
        raw_bytes = response.content

    imagen = Image.open(io.BytesIO(raw_bytes))
    nombre_url = Path(urlparse(target_url).path).name or "latest.gif"
    fecha_hora = _extraer_timestamp_de_nombre(nombre_url)

    logger.info(
        "Descargado URL: %s (%d bytes), timestamp nombre=%s",
        target_url,
        len(raw_bytes),
        fecha_hora,
    )
    return IngestaResultado(
        raw_bytes=raw_bytes,
        fecha_hora=fecha_hora,
        origen="url",
        imagen_pil=imagen,
    )