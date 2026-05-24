# src/main.py
"""
Entry point de la aplicación FastAPI.

Configura:
- Logging estructurado a stdout (12-Factor, Factor XI).
- CORS desde settings.cors_origins_list.
- Routers de la API (auth, imagenes, procesamiento, admin).
- Endpoint de health-check.

Arranque:
    uv run uvicorn src.main:app --reload
    uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4
"""
import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers.auth import router as auth_router
from src.api.routers.imagenes import router as imagenes_router
from src.api.routers.procesamiento import router as procesamiento_router
from src.api.routers.admin import router as admin_router
from src.config import settings

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Radar Weather System v2",
    version="0.1.0",
    description=(
        "API REST para procesamiento de imágenes de radar meteorológico DACC Mendoza. "
        "Convierte GIF/PNG a GeoTIFF georreferenciado mediante un pipeline de 7 fases."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
API_PREFIX = "/api/v1"
app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(imagenes_router, prefix=API_PREFIX)
app.include_router(procesamiento_router, prefix=API_PREFIX)
app.include_router(admin_router, prefix=API_PREFIX)


# ── Endpoints base ────────────────────────────────────────────────────────────

@app.get("/health", tags=["sistema"])
async def health_check() -> dict:
    """Verifica que la API está activa. No requiere autenticación."""
    return {"status": "ok", "version": app.version}


@app.on_event("startup")
async def on_startup() -> None:
    logger.info("Radar Weather System v2 iniciado. Docs: /docs")