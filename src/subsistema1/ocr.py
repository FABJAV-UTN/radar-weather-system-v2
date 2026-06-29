from __future__ import annotations

# src/subsistema1/ocr.py
"""
Extracción de timestamp de imágenes de radar DACC via OCR (Tesseract).

Funciones puras sin I/O de archivos: operan sobre PIL.Image en memoria.
"""
'''
explicación completa del codigo de ocr.py:
El código en ocr.py tiene como objetivo extraer un timestamp de imágenes de radar DACC utilizando OCR (Optical Character Recognition) con la biblioteca Tesseract. 
El proceso se realiza sin realizar operaciones de entrada/salida de archivos, operando directamente sobre objetos PIL.Image en memoria. 
Tiene varias funciones que trabajan juntas para lograr este objetivo: 
1. **_clamp_year(year: int) -> int**:
   - Corrige años fuera del rango válido (2020-2035) que pueden ser mal interpretados por el OCR.
   - Utiliza un mapeo de confusiones comunes de OCR para intentar corregir dígito por dígito y encontrar el año más cercano válido.
   - Si no se puede corregir, se ajusta al límite más cercano del rango válido.
2. **_validate_and_fix_datetime(dt: datetime | None) -> datetime | None**:
   - Valida que los componentes del datetime sean razonables (mes, día, hora, minuto, segundo).
   - Corrige el año si está fuera del rango válido utilizando la función _clamp_year.
3. **extract_timestamp(image: Image.Image) -> datetime | None**:
   - Realiza OCR sobre la imagen completa para extraer texto.
   - Busca patrones de fecha y hora utilizando expresiones regulares.
   - Construye un objeto datetime a partir de los valores extraídos y aplica un offset de zona horaria (UTC-3 para Mendoza).
   - Valida y corrige el datetime utilizando la función _validate_and_fix_datetime.
   - Si falla la extracción principal, intenta un método de fallback más robusto para parsear el timestamp.
4. **_parse_timestamp_fallback(text: str) -> datetime | None**:
   - Proporciona un método alternativo para extraer el timestamp en caso de que la extracción principal falle.
   - Limpia el texto OCR de caracteres no deseados y aplica correcciones comunes de OCR.
   - Intenta varios patrones de fecha y hora para construir un objeto datetime válido.
5. **format_filename(location: str, timestamp: datetime) -> str**:
   - Genera un nombre de archivo normalizado basado en la ubicación y el timestamp extraído, en el formato "lugar_ddmmaa_hhmmss".
En resumen, el código de ocr.py está diseñado para extraer de manera robusta y confiable un timestamp de imágenes de radar DACC, 
corrigiendo errores comunes de OCR y asegurando que los valores extraídos sean válidos y consistentes con el rango esperado.  

'''

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

# Rango válido de años para el radar DACC Mendoza
_YEAR_MIN_VALID = 2020
_YEAR_MAX_VALID = 2035


def _clamp_year(year: int) -> int:
    """
    Corrige años fuera de rango por errores de OCR.

    Tesseract puede confundir dígitos:
    - 2 ↔ 8, 9, 0, 1, 7
    - 0 ↔ 8, 9, 6
    - etc.

    Estrategia: si el año está fuera de [_YEAR_MIN_VALID, _YEAR_MAX_VALID],
    intenta correcciones dígito por dígito buscando el año válido más cercano.
    """
    if _YEAR_MIN_VALID <= year <= _YEAR_MAX_VALID:
        return year

    year_str = str(year)
    if len(year_str) != 4:
        return year  # No podemos corregir si no tiene 4 dígitos

    # Mapeo de confusiones comunes de OCR
    ocr_confusions = {
        '0': ['8', '9', '6'],
        '1': ['7', '4', '9'],
        '2': ['8', '9', '7', '1'],
        '3': ['8', '9'],
        '4': ['1', '9'],
        '5': ['6', '8', '9'],
        '6': ['8', '5', '0'],
        '7': ['1', '2', '9'],
        '8': ['0', '6', '5', '3', '9'],
        '9': ['0', '8', '3', '1', '7'],
    }

    # Intentar correcciones dígito por dígito
    best_year = year
    best_distance = abs(year - ((_YEAR_MIN_VALID + _YEAR_MAX_VALID) // 2))

    for i in range(4):
        original_digit = year_str[i]
        if original_digit not in ocr_confusions:
            continue
        for replacement in ocr_confusions[original_digit]:
            corrected = year_str[:i] + replacement + year_str[i+1:]
            try:
                corrected_year = int(corrected)
                if _YEAR_MIN_VALID <= corrected_year <= _YEAR_MAX_VALID:
                    distance = min(
                        abs(corrected_year - _YEAR_MIN_VALID),
                        abs(corrected_year - _YEAR_MAX_VALID)
                    )
                    if distance < best_distance:
                        best_distance = distance
                        best_year = corrected_year
            except ValueError:
                continue

    # Si sigue fuera de rango, clamp al rango válido
    if best_year < _YEAR_MIN_VALID:
        logger.warning("Año %d corregido a %d (clamp mínimo)", year, _YEAR_MIN_VALID)
        return _YEAR_MIN_VALID
    if best_year > _YEAR_MAX_VALID:
        logger.warning("Año %d corregido a %d (clamp máximo)", year, _YEAR_MAX_VALID)
        return _YEAR_MAX_VALID

    if best_year != year:
        logger.info("Año OCR corregido: %d → %d", year, best_year)

    return best_year


def _validate_and_fix_datetime(dt: datetime | None) -> datetime | None:
    """
    Valida que el datetime tenga componentes razonables y corrige el año si es necesario.

    Returns:
        datetime corregido o None si es inválido.
    """
    if dt is None:
        return None

    # Validar mes y día
    if not (1 <= dt.month <= 12) or not (1 <= dt.day <= 31):
        return None

    # Validar hora
    if not (0 <= dt.hour <= 23) or not (0 <= dt.minute <= 59) or not (0 <= dt.second <= 59):
        return None

    # Corregir año si está fuera de rango
    corrected_year = _clamp_year(dt.year)
    if corrected_year != dt.year:
        try:
            dt = dt.replace(year=corrected_year)
        except ValueError:
            return None

    return dt


def extract_timestamp(image: Image.Image) -> datetime | None:
    """
    Extrae el timestamp de la imagen de radar y lo convierte a hora local (UTC-3).

    Pasos:
    1. OCR sobre imagen completa (RGB).
    2. Buscar fecha con regex YYYY[/-]MM[/-]DD.
    3. Buscar hora con regex HH:MM:SS.
    4. Construir datetime y aplicar offset UTC-3.
    5. Validar y corregir año si OCR produjo valor erróneo.

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

    # Validar y corregir año
    dt_utc = _validate_and_fix_datetime(dt_utc)
    if dt_utc is None:
        logger.warning("Datetime inválido después de parseo, intentando fallback")
        return _parse_timestamp_fallback(text)

    local_dt = dt_utc + timedelta(hours=settings.radar_timezone_offset_hours)
    logger.info("Timestamp UTC: %s → Local UTC-3: %s", dt_utc, local_dt)
    return local_dt


def _parse_timestamp_fallback(text: str) -> datetime | None:
    """
    Parser robusto para casos donde el regex principal falla.

    Corrige errores comunes de OCR:
    - "9096" → "2026" (confusión 9↔2 en el año).
    - "8026" → "2026" (confusión 8↔2 en el año).
    - "2080" → "2026" (confusión 8↔0 y 0↔6 en el año).
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

        # Aplicar corrección de año robusta
        year = _clamp_year(year)

        try:
            dt = datetime(
                year, int(match.group(2)), int(match.group(3)),
                int(match.group(4)), int(match.group(5)), int(match.group(6)),
            )
            dt = _validate_and_fix_datetime(dt)
            if dt:
                return dt + timedelta(hours=settings.radar_timezone_offset_hours)
        except ValueError:
            pass

    # Probar patrones adicionales
    for pattern, fmt in TIMESTAMP_PATTERNS:
        m = re.search(pattern, cleaned)
        if m:
            try:
                dt = datetime.strptime(m.group(1), fmt)
                dt = _validate_and_fix_datetime(dt)
                if dt:
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