# src/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    radar_url: str = "https://www2.contingencias.mendoza.gov.ar/radar/latest.gif"
    template_dir: str = "/app/templates"
    secret_key: str
    ocr_tolerance: float = 0.85
    match_score_min: float = 0.3
    log_level: str = "INFO"
    processing_interval_minutes: int = 10
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    cors_origins: str = "http://localhost:3000,http://localhost:3001"

    class Config:
        env_file = ".env"


settings = Settings()