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

    # ── Auth / JWT ───────────────────────────────────────────────────────────
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:3000,http://localhost:3001"

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