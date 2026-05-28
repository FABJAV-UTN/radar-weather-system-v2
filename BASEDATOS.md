# Base de Datos — Radar Weather System v2

Guía para levantar la base de datos, explorar registros y limpiar datos de radar (preservando usuarios).

---

## Conexión

El sistema usa **PostgreSQL 16 con extensión PostGIS**. Todos los datos viven en el esquema `radar`.

| Parámetro | Valor (desarrollo) |
|---|---|
| Host | `localhost` |
| Puerto | `5432` |
| Base de datos | `radar_db` |
| Usuario | `radar` |
| Contraseña | `radar` |
| Esquema | `radar` |

---

## Levantar la base de datos

### Con Docker (recomendado)

```bash
# Solo la DB (sin levantar backend ni frontend)
docker compose up db -d

# Verificar que está lista
docker compose ps db
```

### Conectarse con psql desde el contenedor

```bash
docker compose exec db psql -U radar -d radar_db
```

### Conectarse con psql desde la máquina host

```bash
psql -h localhost -U radar -d radar_db
```

### Correr las migraciones (primera vez o después de cambios)

```bash
docker compose exec backend uv run alembic upgrade head
```

Para verificar el estado de las migraciones:

```bash
docker compose exec backend uv run alembic current
docker compose exec backend uv run alembic history
```

---

## Tablas del esquema `radar`

```
radar.imagenes_radar          — Tabla central: imágenes y GeoTIFFs
radar.procesamiento_pasos     — Log de cada fase del pipeline por imagen
radar.metricas_procesamiento  — Métricas cuantitativas por imagen
radar.intentos_descarga       — Historial de descargas desde URL DACC
radar.usuarios                — Usuarios del sistema (NO borrar)
radar.sesiones                — Sesiones JWT activas
```

---

## Comandos SQL para ver registros

### Ver imágenes procesadas

```sql
-- Últimas 20 imágenes, sin los blobs binarios
SELECT id, fecha_hora, origen, estado, tiene_marco, score_match, fecha_procesamiento, created_at
FROM radar.imagenes_radar
ORDER BY fecha_hora DESC
LIMIT 20;
```

### Ver solo imágenes completadas

```sql
SELECT id, fecha_hora, origen, score_match, fecha_procesamiento
FROM radar.imagenes_radar
WHERE estado = 'completado'
ORDER BY fecha_hora DESC
LIMIT 50;
```

### Ver imágenes con error

```sql
SELECT id, fecha_hora, origen, estado, created_at
FROM radar.imagenes_radar
WHERE estado = 'error'
ORDER BY created_at DESC;
```

### Ver métricas de procesamiento

```sql
SELECT
    m.imagen_id,
    i.fecha_hora,
    m.pixeles_originales,
    m.pixeles_limpios,
    m.pixeles_rellenados,
    m.pixeles_perdidos,
    m.error_relleno_pct,
    m.dbz_max,
    m.procesado_en
FROM radar.metricas_procesamiento m
JOIN radar.imagenes_radar i ON i.id = m.imagen_id
ORDER BY m.procesado_en DESC
LIMIT 20;
```

### Ver pasos del pipeline de una imagen específica

```sql
-- Reemplazá 42 por el ID de la imagen que querés consultar
SELECT paso, exitoso, mensaje_error, ejecutado_en
FROM radar.procesamiento_pasos
WHERE imagen_id = 42
ORDER BY ejecutado_en ASC;
```

### Ver historial de intentos de descarga URL

```sql
SELECT url, exitoso, motivo_fallo, intento_numero, fecha_intento
FROM radar.intentos_descarga
ORDER BY fecha_intento DESC
LIMIT 50;
```

### Vista resumen del pipeline

```sql
-- Vista preconstruida que combina imagenes + métricas + conteo de pasos
SELECT *
FROM radar.resumen_pipeline
ORDER BY fecha_hora DESC
LIMIT 20;
```

### Ver usuarios (solo lectura, no modificar desde acá)

```sql
SELECT id, username, email, rol, activo, ultimo_login, created_at
FROM radar.usuarios
ORDER BY created_at ASC;
```

### Contar registros por tabla

```sql
SELECT
    'imagenes_radar'         AS tabla, COUNT(*) FROM radar.imagenes_radar
UNION ALL SELECT
    'procesamiento_pasos'    AS tabla, COUNT(*) FROM radar.procesamiento_pasos
UNION ALL SELECT
    'metricas_procesamiento' AS tabla, COUNT(*) FROM radar.metricas_procesamiento
UNION ALL SELECT
    'intentos_descarga'      AS tabla, COUNT(*) FROM radar.intentos_descarga
UNION ALL SELECT
    'usuarios'               AS tabla, COUNT(*) FROM radar.usuarios
UNION ALL SELECT
    'sesiones'               AS tabla, COUNT(*) FROM radar.sesiones;
```

---

## Limpiar registros de radar (preservando usuarios y sesiones)

> ⚠️ Estos comandos borran datos **permanentemente**. Hacé backup antes si necesitás conservar algo.

### Truncate de todas las tablas de radar (respeta el orden por FK)

```sql
-- Borra todo en el orden correcto para respetar las foreign keys
TRUNCATE TABLE
    radar.procesamiento_pasos,
    radar.metricas_procesamiento,
    radar.intentos_descarga,
    radar.imagenes_radar
RESTART IDENTITY CASCADE;
```

Esto limpia todas las imágenes, sus pasos, métricas e intentos de descarga, y reinicia los contadores de autoincremento. Los usuarios y sesiones **no se tocan**.

### Borrar solo los registros de una imagen específica

```sql
-- Reemplazá 42 por el ID de la imagen
DELETE FROM radar.procesamiento_pasos     WHERE imagen_id = 42;
DELETE FROM radar.metricas_procesamiento  WHERE imagen_id = 42;
DELETE FROM radar.imagenes_radar          WHERE id = 42;
```

### Borrar imágenes con error

```sql
-- Primero borrar registros dependientes
DELETE FROM radar.procesamiento_pasos
WHERE imagen_id IN (SELECT id FROM radar.imagenes_radar WHERE estado = 'error');

DELETE FROM radar.metricas_procesamiento
WHERE imagen_id IN (SELECT id FROM radar.imagenes_radar WHERE estado = 'error');

-- Luego borrar las imágenes
DELETE FROM radar.imagenes_radar WHERE estado = 'error';
```

### Borrar intentos de descarga fallidos (sin tocar imágenes)

```sql
DELETE FROM radar.intentos_descarga WHERE exitoso = FALSE;
```

### Limpiar sesiones JWT revocadas

```sql
-- Borra sesiones que ya no están activas
DELETE FROM radar.sesiones WHERE activa = FALSE;
```

---

## Backup y restore

### Backup completo

```bash
docker compose exec db pg_dump -U radar radar_db > backup_$(date +%Y%m%d).sql
```

### Backup solo del esquema radar (sin binarios grandes)

```sql
-- Desde psql, exportar solo estructura y datos de tablas pequeñas
\COPY radar.usuarios TO '/tmp/usuarios.csv' CSV HEADER;
```

### Restore

```bash
docker compose exec -T db psql -U radar radar_db < backup_20260528.sql
```

---

## Notas sobre almacenamiento

La tabla `radar.imagenes_radar` almacena los blobs binarios de las imágenes directamente en la base de datos:

- `raw_data` — imagen GIF/PNG original descargada
- `clean_data` — imagen limpia (solo píxeles dBZ)
- `filled_data` — imagen con huecos del watermark rellenados
- `cropped_data` — imagen recortada (solo si tenía marco)
- `geotiff_data` — GeoTIFF final georreferenciado (el producto principal)

Si la DB crece mucho, podés liberar espacio borrando imágenes antiguas con los comandos de la sección anterior. El `VACUUM` posterior libera el espacio en disco:

```sql
VACUUM FULL radar.imagenes_radar;
```
