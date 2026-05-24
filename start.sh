#!/bin/bash
# start.sh — Levantar todo el stack Radar DACC con Docker Compose

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="radar-weather"

echo "🌩️  Radar Weather System — Docker Compose"
echo "============================================"

# Verificar que Docker está corriendo
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker no está corriendo. Iniciá Docker primero."
    exit 1
fi

# Verificar que existe el frontend
if [ ! -d "$SCRIPT_DIR/frontend_tecnicos" ]; then
    echo "❌ No se encontró frontend_tecnicos/"
    echo "   Descomprimí el frontend_tecnicos_v2.zip primero:"
    echo "   unzip frontend_tecnicos_v2.zip -d frontend_tecnicos/"
    exit 1
fi

# Verificar que existe el backend
if [ ! -d "$SCRIPT_DIR/../radar-weather-system-v2" ] && [ ! -d "$SCRIPT_DIR/radar-weather-system-v2" ]; then
    echo "⚠️  No se encontró radar-weather-system-v2/ en la ruta esperada"
    echo "   Asegurate de que el backend esté en ../radar-weather-system-v2"
fi

echo ""
echo "📦 Servicios:"
echo "   🗄️  db        → PostgreSQL + PostGIS  (puerto 5432)"
echo "   ⚙️  backend   → FastAPI + uv          (puerto 8000)"
echo "   🎨  frontend  → React + Vite          (puerto 3000)"
echo ""

# Opciones
case "${1:-up}" in
    up)
        echo "🚀 Levantando servicios..."
        docker compose -f "$SCRIPT_DIR/docker-compose.full.yml" -p "$PROJECT_NAME" up --build
        ;;
    down)
        echo "🛑 Deteniendo servicios..."
        docker compose -f "$SCRIPT_DIR/docker-compose.full.yml" -p "$PROJECT_NAME" down
        ;;
    logs)
        echo "📋 Logs..."
        docker compose -f "$SCRIPT_DIR/docker-compose.full.yml" -p "$PROJECT_NAME" logs -f
        ;;
    ps)
        echo "📊 Estado..."
        docker compose -f "$SCRIPT_DIR/docker-compose.full.yml" -p "$PROJECT_NAME" ps
        ;;
    *)
        echo "Uso: $0 [up|down|logs|ps]"
        exit 1
        ;;
esac
