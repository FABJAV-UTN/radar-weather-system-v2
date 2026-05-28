# Guía de Desarrollo — Radar Weather System v2

Este documento describe la arquitectura del sistema, los módulos principales y cómo se comunican entre sí.

---

## Visión general

El sistema procesa imágenes GIF/PNG del radar meteorológico del DACC Mendoza y las convierte en archivos GeoTIFF georreferenciados. Está compuesto por un backend FastAPI (Python 3.12), un frontend React, y una base de datos PostgreSQL con PostGIS.

```
Frontend (React)
      │  HTTP / JSON
      ▼
Backend (FastAPI)
      │
      ├── Subsistema 1: Pipeline de procesamiento (7 fases)
      │
      └── Base de datos (PostgreSQL + PostGIS)
```

---

## Backend — Estructura de `src/`

```
src/
├── main.py               # Entry point: FastAPI app, CORS, routers
├── config.py             # Configuración via variables de entorno (pydantic-settings)
├── api/
│   ├── dependencies.py   # Inyección de dependencias (get_db, get_current_user, require_role)
│   ├── routers/
│   │   ├── auth.py       # Login, logout, refresh token, /me
│   │   ├── imagenes.py   # Listado, detalle y descarga de imágenes/GeoTIFFs
│   │   ├── procesamiento.py  # Disparar el pipeline (URL, local, lote, scheduler)
│   │   └── admin.py      # Gestión de usuarios (solo admin)
│   └── schemas/
│       ├── imagen.py     # Pydantic schemas para imagenes y pipeline
│       ├── usuario.py    # Pydantic schemas para usuarios
│       └── token.py      # Pydantic schemas para tokens JWT
├── auth/
│   ├── jwt.py            # Crear y validar tokens JWT (access + refresh)
│   └── security.py       # Hash y verificación de contraseñas (bcrypt)
├── db/
│   ├── models.py         # Modelos SQLAlchemy (ImagenRadar, Usuario, etc.)
│   ├── connection.py     # Engine async y SessionFactory
│   ├── repository.py     # Patrón Repository: toda la lógica SQL
│   ├── repository_ext.py # SesionRepository (JWT sessions)
│   └── sesion_model.py   # Modelo SQLAlchemy para sesiones
└── subsistema1/
    ├── orquestador.py    # Coordinador del pipeline de 7 fases
    ├── ingestor.py       # Fase 1: adquisición (URL DACC o archivo local)
    ├── detector_marco.py # Fase 2: detección del marco DACC
    ├── crop.py           # Fase 3: recorte del marco
    ├── limpiar.py        # Fase 4: limpieza y clasificación dBZ
    ├── rellenar.py       # Fase 5: relleno de huecos (watermark)
    ├── geolocalizar.py   # Fase 6: georreferenciación con template matching
    ├── ocr.py            # Extracción de timestamp via OCR (Tesseract)
    └── scheduler.py      # Procesamiento continuo automático (loop async)
```

---

## Módulos principales y comunicación

### `src/main.py`

Entry point de FastAPI. Configura CORS, logging y registra los cuatro routers bajo el prefijo `/api/v1`. También define el endpoint de health check en `/health`.

### `src/config.py`

Todas las variables de entorno se leen acá con `pydantic-settings`. Genera el objeto singleton `settings` que se importa en cualquier módulo que necesite configuración. Las variables importantes son `DATABASE_URL`, `SECRET_KEY`, `RADAR_URL` y `TEMPLATE_DIR`.

---

### API — Routers

**`auth.py`** gestiona autenticación JWT con access token (15 min) y refresh token (7 días). El login registra una sesión en la tabla `radar.sesiones`. El logout revoca el refresh token. El endpoint `/me` devuelve el usuario autenticado actual.

**`procesamiento.py`** es el router más complejo. Expone endpoints para:
- `POST /procesamiento/url` — pipeline desde URL DACC (una sola imagen)
- `POST /procesamiento/local` — pipeline desde archivo del servidor
- `POST /procesamiento/carpeta` — lote desde carpeta del servidor
- `POST /procesamiento/upload-lote` — lote subido desde el cliente (multipart)
- `POST /procesamiento/lote/cancelar` — señal de cancelación al lote activo
- `POST /procesamiento/scheduler/start` y `/stop` — control del scheduler continuo
- `GET /procesamiento/scheduler/estado` — estado del scheduler

**`imagenes.py`** sirve el listado paginado con filtros (`estado`, `origen`), el detalle de una imagen y la descarga de GeoTIFF individual. También tiene el endpoint `GET /imagenes/descargar-lote` que genera un ZIP con múltiples GeoTIFFs filtrados por rango de fechas.

**`admin.py`** gestiona usuarios (solo rol `admin`): listar, crear, cambiar rol, activar/desactivar y eliminar. También expone el historial de intentos de descarga URL.

---

### Subsistema 1 — Pipeline de procesamiento

El orquestador coordina las 7 fases secuenciales. Cada fase opera en memoria; solo se accede a la base de datos al inicio (crear registro) y al final (guardar GeoTIFF y métricas).

```
Fase 1: ingestor.py
  └─► Descarga latest.gif desde URL DACC (OCR para timestamp)
      ó lee archivo local (timestamp del nombre de archivo)
      └─► Verifica duplicado en DB antes de continuar

Fase 2: detector_marco.py
  └─► Detecta si la imagen tiene el marco DACC (#5e9d9f)
      buscando el color desde los 4 bordes hacia el centro

Fase 3: crop.py  (condicional — solo si tiene marco)
  └─► Recorta el marco detectado en la fase anterior

Fase 4: limpiar.py
  └─► Elimina colores de marco residuales
  └─► Clasifica píxeles por distancia euclidea al mapa dBZ (16 niveles, 10-80 dBZ)
  └─► Genera máscara del watermark (región fija en 0,0,120,30)

Fase 5: rellenar.py
  └─► Rellena los huecos de la máscara (watermark) por interpolación

Fase 6: geolocalizar.py
  └─► Template matching del eco fijo contra template_eco_fijo.tif
  └─► Corrige el Affine Transform según la posición del eco
  └─► Escribe el GeoTIFF final en un buffer BytesIO (LZW comprimido)
  └─► Devuelve clutter_mask para excluir ecos fijos del cálculo de dBZ máximo

Fase 7: Persistencia
  └─► Guarda en DB: geotiff_data, clean_data, filled_data, cropped_data,
      transform_affine, crs, score_match, tiene_marco
  └─► Registra métricas: píxeles originales/limpios/rellenados/perdidos,
      error_relleno_pct, dbz_max (sin ecos fijos)
```

**Nota importante:** las fases CPU-intensivas (2 a 6) se ejecutan en un thread pool con `asyncio.to_thread()` para no bloquear el event loop de FastAPI.

---

### Scheduler (`scheduler.py`)

Corre un loop async indefinido en segundo plano. Descarga y procesa una imagen, espera el intervalo configurado (default 120 segundos) y repite. Si falla por duplicado, OCR inválido o red, espera y reintenta. Se controla desde la API vía `start()`/`stop()`. El estado (último intento, contadores, próximo intento) se expone en `GET /procesamiento/scheduler/estado`.

---

### Base de datos — `src/db/`

**`models.py`** define los modelos SQLAlchemy. Todas las tablas viven en el esquema `radar`:

- `ImagenRadar` — tabla central con los bytes de la imagen en todas sus versiones y el GeoTIFF final
- `ProcesamentoPaso` — log de cada fase ejecutada (éxito/fallo)
- `MetricaProcesamiento` — métricas cuantitativas del pipeline por imagen
- `IntentoDescarga` — log de descargas desde URL DACC
- `Usuario` — usuarios del sistema con rol y estado
- `Sesion` — sesiones activas para refresh tokens (en `sesion_model.py`)

**`repository.py`** implementa el patrón Repository. Toda la lógica SQL vive acá; los routers nunca escriben queries directamente. Hay un repositorio por entidad: `ImagenRadarRepository`, `ProcesamentoPasoRepository`, `MetricaProcesamientoRepository`, `UsuarioRepository`, `IntentoDescargaRepository`.

**`connection.py`** crea el engine asyncpg y el `AsyncSessionLocal` factory que se usa en toda la aplicación. El `pool_size=10` y `max_overflow=20` están configurados para producción.

---

### Autenticación — `src/auth/`

El sistema usa JWT doble token: **access token** de vida corta (15 min, firmado con HS256) y **refresh token** de vida larga (7 días). El refresh token se almacena en la tabla `radar.sesiones` para poder revocar sesiones. La dependencia `get_current_user` en `dependencies.py` valida el Bearer token en cada request protegido. La dependencia `require_role("admin")` restringe endpoints por rol.

---

## Frontend — `frontend_tecnicos/`

React + Vite + Tailwind CSS. Se comunica con el backend a través del proxy de Vite (en desarrollo) configurado en `vite.config.js`, que redirige `/api` a `http://backend:8000`.

```
src/
├── App.jsx              # Router principal con rutas protegidas
├── hooks/
│   └── useAuth.jsx      # Hook de autenticación (estado usuario, login, logout)
├── context/
│   └── LoteContext.jsx  # Estado global del procesamiento por lote
├── services/
│   └── api.js           # Cliente HTTP con auto-refresh de token y cancelación
├── components/
│   └── Layout.jsx       # Sidebar + topbar responsivo
└── pages/
    ├── Login.jsx         # Formulario de login
    ├── Imagenes.jsx      # Tabla paginada con filtros y descarga GeoTIFF
    ├── Procesamiento.jsx # Panel único (URL/local) + scheduler continuo
    ├── ProcesamientoLote.jsx  # Subida y procesamiento de lote con cancelación
    ├── Configuracion.jsx # Gestión de usuarios (solo admin)
    └── Perfil.jsx        # Perfil del usuario logueado
```

### Flujo de autenticación en el frontend

1. `useAuth` revisa si hay `access_token` en `localStorage`
2. Si existe, llama a `/api/v1/auth/me` para validarlo
3. Si el token expiró (401), `api.js` intenta el refresh automáticamente con el `refresh_token`
4. Si el refresh también falla, redirige a `/login`

### Cancelación de lotes

`LoteContext` mantiene un `AbortController` por request. Al cancelar un lote, el frontend primero hace `POST /procesamiento/lote/cancelar` al backend (señal server-side) y luego aborta el fetch con el `AbortController` (cierra la conexión HTTP). El backend detecta la desconexión del cliente via `request.is_disconnected()`.

---

## Flujo completo de una imagen

```
Usuario hace click "Procesar URL"
  → Frontend: POST /api/v1/procesamiento/url
  → Backend: orquestador.ejecutar_pipeline_url(db, url)
    → ingestor: descarga latest.gif, extrae timestamp via OCR
    → DB: crea registro ImagenRadar en estado "pendiente"
    → detectar_marco: busca color #5e9d9f en bordes
    → (si tiene marco) crop: recorta el marco
    → limpiar: elimina colores no-dBZ, clasifica 16 niveles
    → rellenar: interpola píxeles del watermark
    → geolocalizar: template matching → GeoTIFF final
    → DB: actualiza ImagenRadar (estado "completado", bytes del GeoTIFF)
    → DB: guarda MetricaProcesamiento (dbz_max, píxeles, etc.)
  → Backend: devuelve PipelineResponse al frontend
  → Frontend: muestra resultado con score de geolocalización
```
