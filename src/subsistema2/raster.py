# src/subsistema2/raster.py
"""
Lectura del GeoTIFF de dBZ y reproyección a la grilla de cálculo (F2).

El Subsistema 1 guarda cada imagen como GeoTIFF de 1 banda uint8 en
EPSG:3857 (0 = sin dato, 10–80 = niveles dBZ). En 3857 el píxel nominal mide
790 m pero en el terreno mide ~650 m: medir ahí infla las distancias ~21 % y
las áreas ~45 %. Por eso el Subsistema 2 trabaja en EPSG:5344 (D5).

Todas las imágenes se reproyectan a UNA grilla fija (misma esquina, mismo
tamaño de píxel, mismas dimensiones). Así:
  - la máscara de la imagen t-1 y la de t se pueden superponer píxel a píxel
    (el tracker de F3 asocia primero por solapamiento, D9);
  - el jitter y los saltos de georreferenciación quedan absorbidos por el
    transform de cada imagen, no por la grilla.

El remuestreo es por vecino más cercano: los dBZ son categorías de la
paleta y un bilineal inventaría valores que no existen (manual, cap. 4).

Este módulo no toca la base: recibe bytes y devuelve arrays.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.warp import reproject

NODATA = 0


@dataclass(frozen=True)
class Grilla:
    """Grilla regular de cálculo en un CRS métrico (por defecto EPSG:5344)."""

    srid: int
    xmin: float
    ymax: float
    resolucion_m: float
    ancho: int
    alto: int

    def __post_init__(self) -> None:
        if self.resolucion_m <= 0 or self.ancho <= 0 or self.alto <= 0:
            raise ValueError("La grilla necesita resolución, ancho y alto positivos")

    @property
    def crs(self) -> CRS:
        return CRS.from_epsg(self.srid)

    @property
    def transform(self) -> Affine:
        return Affine(self.resolucion_m, 0.0, self.xmin, 0.0, -self.resolucion_m, self.ymax)

    @property
    def shape(self) -> tuple[int, int]:
        return self.alto, self.ancho

    @property
    def area_pixel_km2(self) -> float:
        return self.resolucion_m**2 / 1e6

    @property
    def limites(self) -> tuple[float, float, float, float]:
        """(xmin, ymin, xmax, ymax) en metros."""
        return (self.xmin, self.ymax - self.alto * self.resolucion_m,
                self.xmin + self.ancho * self.resolucion_m, self.ymax)

    def como_dict(self) -> dict:
        return {"srid": self.srid, "xmin": self.xmin, "ymax": self.ymax,
                "resolucion_m": self.resolucion_m, "ancho": self.ancho, "alto": self.alto}

    @classmethod
    def desde_settings(cls) -> Grilla:
        from src.config import settings  # import diferido: el cálculo no exige .env

        return cls(
            srid=settings.s2_srid, xmin=settings.s2_grilla_xmin, ymax=settings.s2_grilla_ymax,
            resolucion_m=settings.s2_resolucion_m,
            ancho=settings.s2_grilla_ancho, alto=settings.s2_grilla_alto,
        )


@dataclass
class RasterDBZ:
    """Una banda de dBZ (uint8, 0 = sin dato) con su georreferencia."""

    datos: np.ndarray
    transform: Affine
    crs: CRS

    @property
    def shape(self) -> tuple[int, int]:
        return self.datos.shape  # type: ignore[return-value]


def leer_geotiff(geotiff_bytes: bytes) -> RasterDBZ:
    """Lee la banda 1 del GeoTIFF que guarda el Subsistema 1 (sin reproyectar)."""
    if not geotiff_bytes:
        raise ValueError("GeoTIFF vacío")
    with rasterio.open(io.BytesIO(geotiff_bytes)) as src:
        if src.crs is None:
            raise ValueError("El GeoTIFF no tiene CRS")
        datos = src.read(1)
        nodata = src.nodata
        if nodata is not None and nodata != NODATA:
            datos = np.where(datos == nodata, NODATA, datos)
        return RasterDBZ(datos=datos.astype(np.uint8, copy=False), transform=src.transform, crs=src.crs)


def reproyectar(raster: RasterDBZ, grilla: Grilla) -> RasterDBZ:
    """Lleva el raster a la grilla fija por vecino más cercano. Lo que cae afuera queda en 0."""
    destino = np.zeros(grilla.shape, dtype=np.uint8)
    reproject(
        source=raster.datos,
        destination=destino,
        src_transform=raster.transform,
        src_crs=raster.crs,
        src_nodata=NODATA,
        dst_transform=grilla.transform,
        dst_crs=grilla.crs,
        dst_nodata=NODATA,
        resampling=Resampling.nearest,
    )
    return RasterDBZ(datos=destino, transform=grilla.transform, crs=grilla.crs)


def cargar_en_grilla(
    geotiff_bytes: bytes,
    grilla: Grilla,
    transform_origen: Affine | None = None,
) -> RasterDBZ:
    """
    GeoTIFF (bytes de imagenes_radar.geotiff_data) → dBZ en la grilla de cálculo.

    transform_origen reemplaza el transform del archivo. Es el gancho para el
    filtro de saltos de georreferenciación (D13): el orquestador (F5) le pasa
    el transform mediano del evento cuando la imagen saltó más de 1 km.
    """
    raster = leer_geotiff(geotiff_bytes)
    if transform_origen is not None:
        raster = RasterDBZ(datos=raster.datos, transform=transform_origen, crs=raster.crs)
    return reproyectar(raster, grilla)
