# src/db/repository.py
"""
Patrón Repository: toda la lógica de acceso a datos en un único lugar.
No hay SQL hardcodeado fuera de este módulo.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ImagenRadar, IntentoDescarga, MetricaProcesamiento, ProcesamentoPaso, Usuario, RolUsuario


# ─────────────────────────────────────────────────────────────────────────────
# ImagenRadar
# ─────────────────────────────────────────────────────────────────────────────

class ImagenRadarRepository:
    """Repositorio para la tabla radar.imagenes_radar."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def crear(
        self,
        fecha_hora: datetime,
        origen: str,
        raw_data: bytes,
    ) -> ImagenRadar:
        """
        Crea un registro nuevo en estado 'pendiente'.

        Args:
            fecha_hora: Timestamp de la imagen (ya en hora local, UTC-3).
            origen: 'local' o 'url'.
            raw_data: Bytes crudos de la imagen GIF/PNG.

        Returns:
            La instancia persistida con el id asignado.
        """
        imagen = ImagenRadar(
            fecha_hora=fecha_hora,
            origen=origen,
            raw_data=raw_data,
            estado="pendiente",
        )
        self._session.add(imagen)
        await self._session.flush()  # Obtiene el id sin hacer commit
        return imagen

    async def obtener_por_id(self, imagen_id: int) -> ImagenRadar | None:
        """Recupera una imagen por su id primario."""
        result = await self._session.execute(
            select(ImagenRadar).where(ImagenRadar.id == imagen_id)
        )
        return result.scalar_one_or_none()

    async def existe_duplicado(self, fecha_hora: datetime, origen: str) -> bool:
        """
        Verifica si ya existe una imagen con la misma fecha/hora y origen.
        Implementa la constraint uq_imagenes_fecha_hora_origen a nivel Python.
        """
        result = await self._session.execute(
            select(ImagenRadar.id).where(
                ImagenRadar.fecha_hora == fecha_hora,
                ImagenRadar.origen == origen,
            )
        )
        return result.scalar_one_or_none() is not None

    # Columnas ordenables que viven en imagenes_radar
    _SORT_COLUMNS_DIRECT: dict[str, object] = {
        "id":     ImagenRadar.id,
        "fecha":  ImagenRadar.fecha_hora,
        "origen": ImagenRadar.origen,
        "estado": ImagenRadar.estado,
    }

    async def listar(
        self,
        estado: str | None = None,
        origen: str | None = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "fecha",
        sort_dir: str = "desc",
    ) -> list[ImagenRadar]:
        """
        Lista imágenes con filtros opcionales, paginación y ordenamiento
        completamente resuelto en la base de datos.

        Args:
            estado: Filtrar por estado ('pendiente', 'procesando', 'completado', 'error').
            origen: Filtrar por origen ('local', 'url').
            limit: Máximo de registros a devolver.
            offset: Desplazamiento para paginación.
            sort_by: Columna de orden ('id', 'fecha', 'origen', 'estado', 'dbz').
            sort_dir: Dirección ('asc' o 'desc').

        Returns:
            Lista de ImagenRadar (o Row cuando se ordena por dbz).
        """
        asc = sort_dir.lower() != "desc"

        if sort_by == "dbz":
            # Ordenar por dbz_max requiere LEFT JOIN con metricas_procesamiento
            # para acceder a registros sin métrica (dbz_max NULL → van al final).
            col = MetricaProcesamiento.dbz_max
            order_expr = col.asc().nulls_last() if asc else col.desc().nulls_last()

            stmt = (
                select(ImagenRadar)
                .outerjoin(
                    MetricaProcesamiento,
                    MetricaProcesamiento.imagen_id == ImagenRadar.id,
                )
            )
            if estado:
                stmt = stmt.where(ImagenRadar.estado == estado)
            if origen:
                stmt = stmt.where(ImagenRadar.origen == origen)
            stmt = stmt.order_by(order_expr).limit(limit).offset(offset)

        else:
            # Columnas directas en imagenes_radar
            col = self._SORT_COLUMNS_DIRECT.get(sort_by, ImagenRadar.fecha_hora)
            order_expr = col.asc() if asc else col.desc()

            stmt = select(ImagenRadar)
            if estado:
                stmt = stmt.where(ImagenRadar.estado == estado)
            if origen:
                stmt = stmt.where(ImagenRadar.origen == origen)
            stmt = stmt.order_by(order_expr).limit(limit).offset(offset)

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def contar(
        self,
        estado: str | None = None,
        origen: str | None = None,
    ) -> int:
        """
        Devuelve el total de registros que coinciden con los filtros,
        sin aplicar limit ni offset. Usado para calcular páginas en el frontend.
        """
        stmt = select(func.count()).select_from(ImagenRadar)
        if estado:
            stmt = stmt.where(ImagenRadar.estado == estado)
        if origen:
            stmt = stmt.where(ImagenRadar.origen == origen)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def listar_por_rango(
        self,
        desde: datetime,
        hasta: datetime,
    ) -> list[ImagenRadar]:
        """
        Lista todas las imágenes cuya fecha_hora esté entre `desde` y `hasta`
        (ambos inclusive), ordenadas por fecha_hora ascendente.
        Usado por el endpoint de descarga masiva ZIP.
        """
        stmt = (
            select(ImagenRadar)
            .where(ImagenRadar.fecha_hora >= desde)
            .where(ImagenRadar.fecha_hora <= hasta)
            .order_by(ImagenRadar.fecha_hora.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def actualizar_estado(self, imagen_id: int, estado: str) -> None:
        """Cambia el estado de una imagen."""
        await self._session.execute(
            update(ImagenRadar)
            .where(ImagenRadar.id == imagen_id)
            .values(estado=estado)
        )

    async def actualizar_completado(
        self,
        imagen_id: int,
        *,
        geotiff_data: bytes,
        clean_data: bytes,
        filled_data: bytes,
        cropped_data: bytes | None,
        transform_affine: str,
        crs: str,
        score_match: float,
        tiene_marco: bool,
    ) -> None:
        """
        Actualiza todos los campos del pipeline cuando una imagen se procesa con éxito.
        Cambia el estado a 'completado' y registra la fecha de procesamiento.
        """
        await self._session.execute(
            update(ImagenRadar)
            .where(ImagenRadar.id == imagen_id)
            .values(
                estado="completado",
                geotiff_data=geotiff_data,
                clean_data=clean_data,
                filled_data=filled_data,
                cropped_data=cropped_data,
                transform_affine=transform_affine,
                crs=crs,
                score_match=score_match,
                tiene_marco=tiene_marco,
                fecha_procesamiento=datetime.utcnow(),
            )
        )

    async def marcar_error(self, imagen_id: int) -> None:
        """Marca una imagen como fallida."""
        await self._session.execute(
            update(ImagenRadar)
            .where(ImagenRadar.id == imagen_id)
            .values(estado="error", fecha_procesamiento=datetime.utcnow())
        )

    async def obtener_geotiff(self, imagen_id: int) -> bytes | None:
        """Devuelve los bytes del GeoTIFF final, o None si no existe."""
        result = await self._session.execute(
            select(ImagenRadar.geotiff_data).where(ImagenRadar.id == imagen_id)
        )
        return result.scalar_one_or_none()


# ─────────────────────────────────────────────────────────────────────────────
# ProcesamentoPaso
# ─────────────────────────────────────────────────────────────────────────────

class ProcesamentoPasoRepository:
    """Repositorio para radar.procesamiento_pasos."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def registrar(
        self,
        imagen_id: int,
        paso: str,
        exitoso: bool = True,
        mensaje_error: str | None = None,
    ) -> ProcesamentoPaso:
        """
        Registra la ejecución de un paso del pipeline.

        Args:
            imagen_id: ID de la imagen procesada.
            paso: Nombre del paso ('limpieza', 'relleno', 'crop', 'geolocalizacion', 'deteccion_marco').
            exitoso: True si el paso finalizó sin error.
            mensaje_error: Detalle del error si exitoso=False.
        """
        registro = ProcesamentoPaso(
            imagen_id=imagen_id,
            paso=paso,
            exitoso=exitoso,
            mensaje_error=mensaje_error,
        )
        self._session.add(registro)
        await self._session.flush()
        return registro

    async def listar_por_imagen(self, imagen_id: int) -> list[ProcesamentoPaso]:
        """Devuelve todos los pasos registrados para una imagen."""
        result = await self._session.execute(
            select(ProcesamentoPaso)
            .where(ProcesamentoPaso.imagen_id == imagen_id)
            .order_by(ProcesamentoPaso.ejecutado_en.asc())
        )
        return list(result.scalars().all())


# ─────────────────────────────────────────────────────────────────────────────
# MetricaProcesamiento
# ─────────────────────────────────────────────────────────────────────────────

class MetricaProcesamientoRepository:
    """Repositorio para radar.metricas_procesamiento."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def guardar(
        self,
        imagen_id: int,
        pixeles_originales: int,
        pixeles_limpios: int,
        pixeles_rellenados: int,
        pixeles_perdidos: int,
        error_relleno_pct: float,
        dbz_max: float | None = None,
    ) -> MetricaProcesamiento:
        """
        Persiste las métricas de calidad del pipeline.

        Args:
            imagen_id: ID de la imagen procesada.
            pixeles_originales: Píxeles con datos dBZ antes de limpiar.
            pixeles_limpios: Píxeles con datos dBZ después de limpiar.
            pixeles_rellenados: Píxeles recuperados por inpainting.
            pixeles_perdidos: Píxeles originales que no se pudieron recuperar.
            error_relleno_pct: Porcentaje de error (perdidos / originales).
            dbz_max: Valor dBZ máximo real (excluidos ecos fijos).

        Returns:
            La instancia persistida.
        """
        metrica = MetricaProcesamiento(
            imagen_id=imagen_id,
            pixeles_originales=pixeles_originales,
            pixeles_limpios=pixeles_limpios,
            pixeles_rellenados=pixeles_rellenados,
            pixeles_perdidos=pixeles_perdidos,
            error_relleno_pct=error_relleno_pct,
            dbz_max=dbz_max,
        )
        self._session.add(metrica)
        await self._session.flush()
        return metrica

    async def obtener_por_imagen(self, imagen_id: int) -> MetricaProcesamiento | None:
        """Devuelve las métricas de una imagen por su ID."""
        result = await self._session.execute(
            select(MetricaProcesamiento).where(MetricaProcesamiento.imagen_id == imagen_id)
        )
        return result.scalar_one_or_none()


# ─────────────────────────────────────────────────────────────────────────────
# IntentoDescarga
# ─────────────────────────────────────────────────────────────────────────────

class IntentoDescargaRepository:
    """Repositorio para radar.intentos_descarga."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def registrar(
        self,
        url: str,
        exitoso: bool,
        motivo_fallo: str | None = None,
    ) -> IntentoDescarga:
        """Registra un intento de descarga desde la URL DACC."""
        # Contar intentos previos para esta URL
        count_result = await self._session.execute(
            select(func.count()).select_from(IntentoDescarga).where(IntentoDescarga.url == url)
        )
        numero = (count_result.scalar_one() or 0) + 1

        intento = IntentoDescarga(
            url=url,
            exitoso=exitoso,
            motivo_fallo=motivo_fallo,
            intento_numero=numero,
        )
        self._session.add(intento)
        await self._session.flush()
        return intento

    async def listar_recientes(self, limit: int = 20) -> list[IntentoDescarga]:
        """Devuelve los intentos más recientes, ordenados por fecha descendente."""
        result = await self._session.execute(
            select(IntentoDescarga)
            .order_by(IntentoDescarga.fecha_intento.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


# ─────────────────────────────────────────────────────────────────────────────
# Usuario
# ─────────────────────────────────────────────────────────────────────────────

class UsuarioRepository:
    """Repositorio para radar.usuarios."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def crear(
        self,
        username: str,
        email: str,
        password_hash: str,
        rol: RolUsuario,
    ) -> Usuario:
        """Crea un nuevo usuario activo."""
        usuario = Usuario(
            username=username,
            email=email,
            password_hash=password_hash,
            rol=rol,
            activo=True,
        )
        self._session.add(usuario)
        await self._session.flush()
        return usuario

    async def obtener_por_id(self, usuario_id: int) -> Usuario | None:
        """Recupera un usuario por su ID."""
        result = await self._session.execute(
            select(Usuario).where(Usuario.id == usuario_id)
        )
        return result.scalar_one_or_none()

    async def obtener_por_username(self, username: str) -> Usuario | None:
        """Recupera un usuario por su username."""
        result = await self._session.execute(
            select(Usuario).where(Usuario.username == username)
        )
        return result.scalar_one_or_none()

    async def obtener_por_email(self, email: str) -> Usuario | None:
        """Recupera un usuario por su email."""
        result = await self._session.execute(
            select(Usuario).where(Usuario.email == email)
        )
        return result.scalar_one_or_none()

    async def listar(
        self,
        activo: bool | None = None,
        rol: RolUsuario | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Usuario]:
        """Lista usuarios con filtros opcionales."""
        stmt = select(Usuario)
        if activo is not None:
            stmt = stmt.where(Usuario.activo == activo)
        if rol is not None:
            stmt = stmt.where(Usuario.rol == rol)
        stmt = stmt.order_by(Usuario.username.asc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def cambiar_rol(self, usuario_id: int, rol: RolUsuario) -> None:
        """Cambia el rol de un usuario."""
        await self._session.execute(
            update(Usuario).where(Usuario.id == usuario_id).values(rol=rol)
        )

    async def cambiar_estado(self, usuario_id: int, activo: bool) -> None:
        """Activa o desactiva un usuario."""
        await self._session.execute(
            update(Usuario).where(Usuario.id == usuario_id).values(activo=activo)
        )

    async def actualizar_ultimo_login(self, usuario_id: int) -> None:
        """Registra la fecha/hora del último login exitoso."""
        await self._session.execute(
            update(Usuario)
            .where(Usuario.id == usuario_id)
            .values(ultimo_login=datetime.utcnow())
        )

    async def eliminar(self, usuario_id: int) -> None:
        """Elimina un usuario del sistema."""
        from sqlalchemy import delete
        await self._session.execute(
            delete(Usuario).where(Usuario.id == usuario_id)
        )
