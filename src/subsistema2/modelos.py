# src/subsistema2/modelos.py
"""
Objetos en memoria del Subsistema 2.

No dependen de la base: el detector y (desde F3) el tracker trabajan con
estos objetos, y el orquestador los convierte a filas con los repositorios.
Asociacion y Track se agregan en F3, cuando se diseñe el tracker.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # solo para tipos: evita importar SQLAlchemy al calcular
    from src.db.repository_tracking import CeldaNueva


@dataclass(frozen=True)
class Celda:
    """
    Un eco ≥ D1 dBZ en una imagen: una componente conexa de la máscara.

    Coordenadas en metros en el CRS de la grilla (EPSG:5344) salvo lon/lat.
    """

    numero: int                 # etiqueta en la matriz de etiquetas (1..n)
    n_pixeles: int
    area_km2: float
    area_nucleo_km2: float      # píxeles ≥ D2 (45 dBZ)
    n_nucleos: int              # componentes conexas ≥ D2 dentro de la celda
    dbz_max: int
    dbz_medio: float            # promedio en Z lineal, convertido a dBZ
    x_m: float                  # centroide ponderado por Z (D6)
    y_m: float
    lon: float
    lat: float
    x_geom_m: float             # centroide geométrico (referencia)
    y_geom_m: float
    bbox: tuple[float, float, float, float]   # (xmin, ymin, xmax, ymax) en m
    poligono_wkt: str           # MULTIPOLYGON en el CRS de la grilla
    elongacion: float           # √(λ1/λ2); ~1 = redonda
    orientacion_deg: float      # azimut del eje mayor, 0–180 desde el norte

    def a_celda_nueva(
        self, imagen_id: int, fecha_hora: datetime, geo_corregida: bool = False
    ) -> CeldaNueva:
        """Lo que espera CeldaTormentaRepository.crear_varias()."""
        from src.db.repository_tracking import CeldaNueva

        return CeldaNueva(
            imagen_id=imagen_id, numero=self.numero, fecha_hora=fecha_hora,
            x_m=self.x_m, y_m=self.y_m, poligono_wkt=self.poligono_wkt,
            n_pixeles=self.n_pixeles, area_km2=self.area_km2, dbz_max=self.dbz_max,
            dbz_medio=self.dbz_medio, area_nucleo_km2=self.area_nucleo_km2,
            geo_corregida=geo_corregida,
        )
