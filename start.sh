#!/bin/bash
# start.sh — Levantar todo el sistema con Docker

echo "🛰️  Sistema Radar DACC — Iniciando..."
echo ""

# Verificar que Docker está corriendo
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker no está corriendo. Inicializalo primero:"
    echo "   sudo systemctl start docker"
    exit 1
fi

# Copiar archivos del frontend al proyecto si es necesario
if [ ! -d "frontend_tecnicos" ]; then
    echo "⚠️  No se encontró frontend_tecnicos/ en el proyecto"
    echo "   Copiando desde /mnt/agents/output/frontend_tecnicos..."
    cp -r /mnt/agents/output/frontend_tecnicos ./frontend_tecnicos 2>/dev/null || {
        echo "❌ No se pudo copiar. Asegurate de tener los archivos del frontend."
        exit 1
    }
fi

# Levantar todo
echo "📦 Construyendo imágenes y levantando servicios..."
docker compose -f docker-compose-full.yml up --build -d

echo ""
echo "✅ Todo listo!"
echo ""
echo "   🌐 Frontend:  http://localhost:3000"
echo "   ⚙️  API:       http://localhost:8000/docs"
echo "   🗄️  DB:        localhost:5432"
echo ""
echo "📋 Logs: docker compose -f docker-compose-full.yml logs -f"
echo "🛑 Parar: docker compose -f docker-compose-full.yml down"
