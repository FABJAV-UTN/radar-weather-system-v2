from __future__ import annotations

# src/subsistema1/scheduler.py
"""
Scheduler de procesamiento continuo desde URL DACC (Ruta B).

Según la guía de diseño:
- Descarga latest.gif, procesa, espera PROCESSING_INTERVAL_MINUTES (default: 2 min).
- Si falla por cualquier motivo (OCR inválido, duplicado, red, etc.),
  igual espera el intervalo y reintenta.
- Expone start/stop para control desde la API.
"""

import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Estado global del scheduler ──────────────────────────────────────────────

_task: asyncio.Task | None = None
_running: bool = False
_ultimo_intento: datetime | None = None
_ultimo_resultado: str = "Sin intentos aún"
_total_exitosos: int = 0
_total_fallidos: int = 0
_intervalo_segundos: int = 120  # 2 minutos por defecto


def get_estado() -> dict:
    """Devuelve el estado actual del scheduler."""
    return {
        "activo": _running,
        "ultimo_intento": _ultimo_intento.isoformat() if _ultimo_intento else None,
        "ultimo_resultado": _ultimo_resultado,
        "total_exitosos": _total_exitosos,
        "total_fallidos": _total_fallidos,
        "intervalo_segundos": _intervalo_segundos,
        "proximo_intento_en": _calcular_proximo(),
    }


def _calcular_proximo() -> int | None:
    """Segundos hasta el próximo intento (aproximado)."""
    if not _running or _ultimo_intento is None:
        return None
    transcurridos = (datetime.utcnow() - _ultimo_intento).total_seconds()
    restantes = max(0, _intervalo_segundos - int(transcurridos))
    return restantes


async def _loop(url: str | None, intervalo: int) -> None:
    """Loop principal del scheduler. Corre indefinidamente hasta que se llame a stop()."""
    global _running, _ultimo_intento, _ultimo_resultado, _total_exitosos, _total_fallidos

    from src.db.connection import AsyncSessionLocal
    from src.subsistema1.orquestador import ejecutar_pipeline_url

    logger.info("Scheduler iniciado — intervalo=%ds url=%s", intervalo, url or "default")

    while _running:
        _ultimo_intento = datetime.utcnow()

        try:
            async with AsyncSessionLocal() as session:
                resultado = await ejecutar_pipeline_url(session, url=url)
                await session.commit()

            if resultado.exito:
                _total_exitosos += 1
                _ultimo_resultado = f"✅ OK — imagen #{resultado.imagen_id} (score={resultado.metricas.score_match:.2f})"
                logger.info("Scheduler — ciclo OK: imagen #%d", resultado.imagen_id)
            else:
                _total_fallidos += 1
                _ultimo_resultado = f"⚠️ Pipeline falló: {resultado.mensaje_error[:120]}"
                logger.warning("Scheduler — pipeline falló: %s", resultado.mensaje_error)

        except ValueError as e:
            # Duplicado u OCR inválido — es esperado, no es un error grave
            _total_fallidos += 1
            _ultimo_resultado = f"ℹ️ Saltado: {str(e)[:120]}"
            logger.info("Scheduler — ciclo saltado: %s", e)

        except asyncio.CancelledError:
            logger.info("Scheduler — cancelado")
            break

        except Exception as e:
            _total_fallidos += 1
            _ultimo_resultado = f"❌ Error inesperado: {type(e).__name__}: {str(e)[:100]}"
            logger.exception("Scheduler — error inesperado: %s", e)

        if not _running:
            break

        # Esperar el intervalo, pero salir limpiamente si se cancela
        try:
            await asyncio.sleep(intervalo)
        except asyncio.CancelledError:
            break

    _running = False
    logger.info("Scheduler detenido — exitosos=%d fallidos=%d", _total_exitosos, _total_fallidos)


def start(url: str | None = None, intervalo_segundos: int = 120) -> bool:
    """
    Inicia el scheduler en background.

    Args:
        url: URL alternativa. Si None, usa RADAR_URL del config.
        intervalo_segundos: Segundos entre cada ciclo de descarga.

    Returns:
        True si se inició, False si ya estaba corriendo.
    """
    global _task, _running, _intervalo_segundos, _total_exitosos, _total_fallidos

    if _running:
        return False

    _running = True
    _intervalo_segundos = intervalo_segundos
    _total_exitosos = 0
    _total_fallidos = 0

    loop = asyncio.get_event_loop()
    _task = loop.create_task(_loop(url, intervalo_segundos))
    return True


def stop() -> bool:
    """
    Detiene el scheduler.

    Returns:
        True si se detuvo, False si no estaba corriendo.
    """
    global _task, _running

    if not _running:
        return False

    _running = False
    if _task and not _task.done():
        _task.cancel()
    _task = None
    return True
