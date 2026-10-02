# src/config.py
"""
Configuración centralizada via variables de entorno (12-Factor App, Factor III).
Toda configuración se lee desde .env o el entorno del proceso.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Base de datos ─────────────────────────────────────────────────────────
    database_url: str  # postgresql+asyncpg://...

    # ── Radar DACC ───────────────────────────────────────────────────────────
    radar_url: str = "https://www2.contingencias.mendoza.gov.ar/radar/latest.gif"
    radar_location: str = "san_rafael"
    processing_interval_minutes: int = 10

    # ── Templates geoespaciales ───────────────────────────────────────────────
    template_dir: str = "/app/templates"
    # Umbral de ancho para elegir tif700 vs tif800
    template_width_threshold: int = 799
    # Score mínimo aceptable de template matching
    match_score_min: float = 0.3

    # ── Radar débil / eco verde ─────────────────────────────────────────────────
    weak_precip_hue_min: int = 35
    weak_precip_hue_max: int = 85
    weak_precip_sat_min: int = 100
    weak_precip_val_min: int = 80

    # ── OCR ──────────────────────────────────────────────────────────────────
    ocr_tolerance: float = 0.85
    # Offset UTC→Mendoza (UTC-3)
    radar_timezone_offset_hours: int = -3

    # ── Limpieza de imagen ───────────────────────────────────────────────────
    color_threshold: float = 30.0

    # ── Subsistema 2: detección de celdas (F2) ───────────────────────────────
    # Decisiones D1–D6 del plan. Se guardan en ejecuciones_tracking.parametros.
    s2_umbral_dbz: float = 35.0          # D1: píxel de celda si dBZ >= umbral
    s2_umbral_nucleo_dbz: float = 45.0   # D2: núcleo intenso dentro de la celda
    s2_area_min_km2: float = 4.0         # D3: celdas más chicas se descartan
    s2_conectividad: int = 8             # D4: 4 u 8 vecinos
    s2_srid: int = 5344                  # D5: POSGAR 2007 / Argentina faja 2
    # Grilla fija de cálculo en EPSG:5344: todas las imágenes se reproyectan a
    # la MISMA grilla, así las máscaras de t-1 y t se pueden superponer (F3).
    # Cubre el marco más grande del radar (template tif800: lon −70,7° a −65,1°,
    # lat −36,7° a −31,3°) con ~10 km de margen. 847 × 954 píxeles de 650 m.
    s2_resolucion_m: float = 650.0
    s2_grilla_xmin: float = 2_330_000.0
    s2_grilla_ymax: float = 6_550_100.0
    s2_grilla_ancho: int = 847
    s2_grilla_alto: int = 954

    # ── Auth / JWT ───────────────────────────────────────────────────────────
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:3000,http://localhost:3001"

    # ── Usuario de laboratorio ───────────────────────────────────────────────
    # Si no existe el usuario 'admin', se crea al arrancar con contraseña 'admin'.
    # Pensado para las PCs del laboratorio. En producción: SEED_ADMIN=false.
    seed_admin: bool = True
    seed_admin_username: str = "admin"
    seed_admin_password: str = "admin"

    # ── Servidor ─────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    @property
    def cors_origins_list(self) -> list[str]:
        """Devuelve la lista de orígenes CORS como lista Python."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()