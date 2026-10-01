# Radar Weather System v2

Sistema de procesamiento de imágenes de radar meteorológico del DACC Mendoza. Convierte imágenes GIF/PNG en GeoTIFF georreferenciado mediante un pipeline de 7 fases.

---

## Requisitos previos

Antes de levantar el proyecto necesitás tener instalado:

- **Docker** (con el plugin Compose, versión `docker compose` no `docker-compose`)
- **uv** — gestor de paquetes Python moderno (necesario para desarrollo local y para correr migraciones fuera del contenedor)

### Instalar uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verificar instalación:

```bash
uv --version
```

---

## Estructura del proyecto

```
radar-weather-system-v2/
├── src/                    # Backend Python (FastAPI)
│   ├── main.py
│   ├── config.py
│   ├── subsistema1/        # Pipeline de procesamiento
│   ├── api/                # Routers y schemas
│   ├── auth/               # JWT + seguridad
│   └── db/                 # Modelos, conexión, repositorios
├── frontend_tecnicos/      # Frontend React (Vite + Tailwind)
├── alembic/                # Migraciones de base de datos
├── templates/              # Templates GeoTIFF para geolocalización
├── Dockerfile.backend
├── docker-compose.yml
└── pyproject.toml
```

---

## Levantar el proyecto con Docker

### 1. Clonar y entrar al proyecto

```bash
cd radar-weather-system-v2
```

### 2. (Opcional) Crear el archivo `.env`

El proyecto lee configuración desde variables de entorno. El `docker-compose.yml` ya tiene valores por defecto para desarrollo. Si querés personalizar algo, podés crear un `.env` en la raíz:

```env
DATABASE_URL=postgresql+asyncpg://radar:radar@db:5432/radar_db
SECRET_KEY=radar-secret-key-cambiar-en-produccion-32-chars-min
RADAR_URL=https://www2.contingencias.mendoza.gov.ar/radar/latest.gif
CORS_ORIGINS=http://localhost:3000,http://frontend:3000
```

> ⚠️ En producción, **cambiá el `SECRET_KEY`** por uno seguro de al menos 32 caracteres.

### 3. Construir y levantar todos los servicios

```bash
docker compose up --build
```

Esto levanta tres servicios:
- **db** — PostgreSQL 16 con extensión PostGIS
- **backend** — FastAPI en el puerto `8000`
- **frontend** — React (Vite dev server) en el puerto `3000`

Para correr en segundo plano:

```bash
docker compose up --build -d
```

### 4. Migraciones y usuario (automático)

Al arrancar, el backend aplica solo las migraciones pendientes (`alembic upgrade head`) y,
si no existe, crea el usuario de laboratorio **admin / admin**. Si después le cambiás la
contraseña, no se pisa. En producción se desactiva con `SEED_ADMIN=false`.

Para volver a dejar el admin en admin / admin:

```bash
docker compose exec backend uv run --no-dev python -m src.scripts.reset_admin
```

---

## Acceder al backend

| Recurso | URL |
|---|---|
| API REST | http://localhost:8000/api/v1 |
| Documentación interactiva (Swagger) | http://localhost:8000/docs |
| Documentación alternativa (ReDoc) | http://localhost:8000/redoc |
| Health check | http://localhost:8000/health |

### Verificar que el backend está activo

```bash
curl http://localhost:8000/health
# Respuesta esperada: {"status":"ok","version":"0.1.0"}
```

---

## Acceder al frontend

El frontend de técnicos está disponible en:

**http://localhost:3000**

Iniciá sesión con **admin / admin** (se crea solo al arrancar) o con otro usuario registrado. Los roles disponibles son `admin`, `operador` y `visualizador`.

> El frontend corre con hot reload en modo desarrollo. Los cambios en `frontend_tecnicos/src/` se reflejan automáticamente sin reiniciar el contenedor.

### Resetear o crear el usuario admin

Cada máquina tiene su propia base PostgreSQL en Docker, así que la contraseña del admin puede no coincidir entre equipos. Para dejar el admin con una contraseña conocida (lo crea si no existe, sin tocar el resto de los datos), con los contenedores levantados:

```bash
# contraseña elegida por vos (mínimo 8 caracteres)
docker compose exec backend uv run --no-dev python -m src.scripts.reset_admin --password "tuClave12"

# o dejar que genere una aleatoria (la muestra una sola vez)
docker compose exec backend uv run --no-dev python -m src.scripts.reset_admin
```

> También acepta `--username` y `--email` (por defecto `admin` / `admin@admin.com`).

---

## Comandos útiles

### Ver logs de los servicios

```bash
# Todos los servicios
docker compose logs -f

# Solo el backend
docker compose logs -f backend

# Solo el frontend
docker compose logs -f frontend
```

### Detener los servicios

```bash
docker compose down
```

Para detener **y borrar los volúmenes** (la base de datos incluida):

```bash
docker compose down -v
```

### Reiniciar un servicio específico

```bash
docker compose restart backend
```

### Entrar al contenedor del backend

```bash
docker compose exec backend bash
```

---

## Desarrollo local sin Docker (solo backend)

Si necesitás correr el backend localmente para desarrollo:

```bash
# Instalar dependencias
uv sync

# Asegurarse de tener la DB corriendo (puede ser el contenedor de Docker)
docker compose up db -d

# Correr las migraciones (con la URL local)
uv run alembic upgrade head

# Levantar el backend con hot reload
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### Correr los tests

```bash
uv run pytest
uv run pytest -v                          # verbose
uv run pytest tests/unit/                 # solo tests unitarios
uv run pytest tests/integration/          # solo tests de integración
uv run pytest tests/e2e/                  # solo tests end-to-end
```
