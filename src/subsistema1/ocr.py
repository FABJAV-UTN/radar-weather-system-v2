# src/subsistema1/ocr.py
"""
Extracción de timestamp de imágenes de radar DACC via OCR (Tesseract).

Funciones puras sin I/O de archivos: operan sobre PIL.Image en memoria.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from PIL import Image

from src.config import settings

logger = logging.getLogger(__name__)

# Patrones de timestamp como fallback si el regex principal falla
TIMESTAMP_PATTERNS: list[tuple[str, str]] = [
    (r"(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})", "%Y/%m/%d %H:%M:%S"),
    (r"(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})", "%d/%m/%Y %H:%M"),
    (r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", "%Y-%m-%d %H:%M"),
    (r"(\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2})", "%d-%m-%y %H:%M"),
]


def extract_timestamp(image: Image.Image) -> datetime | None:
    """
    Extrae el timestamp de la imagen de radar y lo convierte a hora local (UTC-3).

    Pasos:
    1. OCR sobre imagen completa (RGB).
    2. Buscar fecha con regex YYYY[/-]MM[/-]DD.
    3. Buscar hora con regex HH:MM:SS.
    4. Construir datetime y aplicar offset UTC-3.

    Args:
        image: Imagen PIL (cualquier modo; se convierte a RGB internamente).

    Returns:
        datetime en UTC-3 (Mendoza), o None si el OCR falló.
    """
    try:
        import pytesseract
    except ImportError:
        logger.error("pytesseract no instalado. Ejecutá: pip install pytesseract")
        return None

    rgb_image = image.convert("RGB")
    raw_text = pytesseract.image_to_string(rgb_image)
    text = " ".join(raw_text.split())
    logger.debug("OCR raw text: %r", text)

    # Buscar fecha: YYYY-MM-DD o YYYY/MM/DD
    date_match = re.search(r"(\d{4})[/-](\d{2})[/-](\d{2})", text)
    if not date_match:
        logger.warning("No se encontró fecha en OCR; intentando fallback.")
        return _parse_timestamp_fallback(text)

    year = int(date_match.group(1))
    month = int(date_match.group(2))
    day = int(date_match.group(3))

    # Buscar hora: HH:MM:SS
    time_match = re.search(r"(\d{2}):(\d{2}):(\d{2})", text)
    if not time_match:
        logger.warning("No se encontró hora en OCR; intentando fallback.")
        return _parse_timestamp_fallback(text)

    hour = int(time_match.group(1))
    minute = int(time_match.group(2))
    second = int(time_match.group(3))

    try:
        dt_utc = datetime(year, month, day, hour, minute, second)
    except ValueError as e:
        logger.error("Error construyendo datetime: %s", e)
        return None

    local_dt = dt_utc + timedelta(hours=settings.radar_timezone_offset_hours)
    logger.info("Timestamp UTC: %s → Local UTC-3: %s", dt_utc, local_dt)
    return local_dt


def _parse_timestamp_fallback(text: str) -> datetime | None:
    """
    Parser robusto para casos donde el regex principal falla.

    Corrige errores comunes de OCR:
    - "9096" → "2026" (confusión 9↔2 en el año).
    - "+" → ":" (ruido OCR).
    - ";" → ":" (confusión de caracteres).

    Args:
        text: Texto extraído por OCR.

    Returns:
        datetime parseado, o None si no se puede parsear.
    """
    cleaned = re.sub(r"[^\d/:.+ -]", "", text).strip()
    cleaned = cleaned.replace("+", ":").replace(";", ":").replace("ː", ":")
    logger.debug("Texto limpio para fallback: %r", cleaned)

    # Intentar patrón robusto: YYYY.MM.DD HH.MM.SS (cualquier separador)
    match = re.search(r"(\d{4}).(\d{2}).(\d{2})\s+(\d{2}).(\d{2}).(\d{2})", cleaned)
    if match:
        year_text = match.group(1)
        year = int(year_text)
        # Corrección OCR: año > 2100 empezando con "9" → reemplazar por "2"
        if year > 2100 and year_text.startswith("9"):
            year = int("2" + year_text[1:])
            logger.debug("Corrección año OCR: %s → %d", year_text, year)
        try:
            dt = datetime(
                year, int(match.group(2)), int(match.group(3)),
                int(match.group(4)), int(match.group(5)), int(match.group(6)),
            )
            return dt + timedelta(hours=settings.radar_timezone_offset_hours)
        except ValueError:
            pass

    # Probar patrones adicionales
    for pattern, fmt in TIMESTAMP_PATTERNS:
        m = re.search(pattern, cleaned)
        if m:
            try:
                dt = datetime.strptime(m.group(1), fmt)
                return dt + timedelta(hours=settings.radar_timezone_offset_hours)
            except ValueError:
                continue

    logger.warning("Fallback: no se pudo parsear timestamp: %r", cleaned)
    return None


def format_filename(location: str, timestamp: datetime) -> str:
    """
    Genera nombre de archivo normalizado: lugar_ddmmaa_hhmmss.

    Args:
        location: Nombre del lugar (ej: 'san_rafael').
        timestamp: datetime en hora local.

    Returns:
        Nombre sin extensión (ej: 'san_rafael_040526_203000').
    """
    return f"{location}_{timestamp.strftime('%d%m%y_%H%M%S')}"