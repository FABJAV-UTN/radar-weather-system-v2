# src/api/vista_dbz.py
"""
Vista liviana del GeoTIFF dBZ para el frontend.

El navegador no puede leer GeoTIFF, así que la banda dBZ se entrega como PNG
en escala de grises SIN pérdida: el valor de cada píxel es el dBZ (0 = sin
dato, 10-80 = niveles). El frontend le aplica la paleta y puede activar o
desactivar niveles sin volver a pedir la imagen.

Para apoyar el cuadro sobre un mapa web se informan además sus límites en
grados (oeste, sur, este, norte). Los GeoTIFF del pipeline están en
EPSG:3857, la misma proyección de los mapas web, así que el cuadro calza
sin deformarse.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import transform_bounds


@dataclass(frozen=True)
class VistaDbz:
    png: bytes
    limites: tuple[float, float, float, float] | None  # oeste, sur, este, norte (grados)


def geotiff_a_vista(geotiff_bytes: bytes) -> VistaDbz:
    """Banda 1 (dBZ, uint8) → PNG de 8 bits en gris + límites en EPSG:4326."""
    with rasterio.MemoryFile(geotiff_bytes) as memoria, memoria.open() as src:
        banda = src.read(1)
        limites = (
            tuple(round(v, 6) for v in transform_bounds(src.crs, "EPSG:4326", *src.bounds))
            if src.crs is not None else None
        )
    buffer = io.BytesIO()
    Image.fromarray(banda.astype(np.uint8), mode="L").save(buffer, format="PNG")
    return VistaDbz(png=buffer.getvalue(), limites=limites)
