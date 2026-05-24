# 🐳 Docker — Sistema Completo

Este setup levanta **todos los servicios** del Sistema Radar en contenedores Docker:

| Servicio | Puerto | Descripción |
|----------|--------|-------------|
| `db` | `5432` | PostgreSQL + PostGIS |
| `backend` | `8000` | API FastAPI (Python) |
| `frontend` | `3000` | React app (nginx) |

## 🚀 Levantar todo

```bash
# Opción 1: Script automático
chmod +x start.sh
./start.sh

# Opción 2: Manual
docker compose -f docker-compose-full.yml up --build -d
```

## 🌐 Acceso

- **App web**: http://localhost:3000
- **API docs**: http://localhost:8000/docs
- **Base de datos**: `postgresql://radar:radar@localhost:5432/radar_db`

## 📋 Comandos útiles

```bash
# Ver logs
docker compose -f docker-compose-full.yml logs -f

# Ver logs de un servicio específico
docker compose -f docker-compose-full.yml logs -f frontend

# Parar todo
docker compose -f docker-compose-full.yml down

# Parar y borrar datos (⚠️ cuidado)
docker compose -f docker-compose-full.yml down -v

# Reconstruir solo el frontend
docker compose -f docker-compose-full.yml up --build frontend -d
```

## 🔧 Desarrollo local (sin Docker)

Si querés desarrollar el frontend sin Docker, necesitás Node.js:

```bash
# Instalar Node 20
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Verificar
node --version  # v20.x.x
npm --version

# Instalar dependencias y levantar
cd frontend_tecnicos
npm install
npm run dev        # http://localhost:3000
```

En desarrollo local, el proxy de Vite redirige `/api` al backend en `localhost:8000`.

## 🏗️ Arquitectura

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   Navegador  │──────▶│  Frontend   │──────▶│   Backend   │
│              │      │   (nginx)     │      │  (FastAPI)  │
│ localhost:3000│    │  localhost:3000│   │ localhost:8000│
└─────────────┘      └─────────────┘      └──────┬──────┘
                                                   │
                                            ┌──────▼──────┐
                                            │     DB      │
                                            │ (PostGIS)   │
                                            │  localhost  │
                                            └─────────────┘
```

El nginx del frontend hace **proxy inverso** de `/api/*` al backend, así el navegador habla siempre con `localhost:3000`.
