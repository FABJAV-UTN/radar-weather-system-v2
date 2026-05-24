# src/db/models.py
"""
Modelos SQLAlchemy que reflejan exactamente el esquema radar_db.sql.
Esquema PostgreSQL: `radar`
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum as SQLEnum,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RolUsuario(str, Enum):
    """Roles disponibles para usuarios del sistema."""
    ADMIN = "admin"
    OPERADOR = "operador"
    VISUALIZADOR = "visualizador"


class ImagenRadar(Base):
    """
    Tabla principal: almacena bytes de imágenes en todas las etapas del pipeline.
    Corresponde a radar.imagenes_radar en radar_db.sql.
    """

    __tablename__ = "imagenes_radar"
    __table_args__ = (
        UniqueConstraint("fecha_hora", "origen", name="uq_imagenes_fecha_hora_origen"),
        CheckConstraint("origen IN ('local', 'url')", name="ck_imagenes_origen"),
        CheckConstraint(
            "estado IN ('pendiente', 'procesando', 'completado', 'error')",
            name="ck_imagenes_estado",
        ),
        {"schema": "radar"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fecha_hora: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    origen: Mapped[str] = mapped_column(String(10), nullable=False)
    estado: Mapped[str] = mapped_column(String(15), nullable=False, default="pendiente", index=True)

    # ── Bytes de imágenes ────────────────────────────────────────────────────
    raw_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    geotiff_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    clean_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    filled_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    cropped_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # ── Metadatos geoespaciales ──────────────────────────────────────────────
    transform_affine: Mapped[str | None] = mapped_column(Text, nullable=True)
    crs: Mapped[str | None] = mapped_column(String(50), nullable=True)
    score_match: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    tiene_marco: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # ── Timestamps ───────────────────────────────────────────────────────────
    fecha_procesamiento: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    def __repr__(self) -> str:
        return f"<ImagenRadar id={self.id} fecha={self.fecha_hora} estado={self.estado}>"


class ProcesamentoPaso(Base):
    """
    Registro de cada paso ejecutado del pipeline.
    ON DELETE SET NULL → si se borra la imagen, el paso queda como registro histórico.
    Corresponde a radar.procesamiento_pasos.
    """

    __tablename__ = "procesamiento_pasos"
    __table_args__ = (
        CheckConstraint(
            "paso IN ('limpieza', 'relleno', 'crop', 'geolocalizacion', 'deteccion_marco')",
            name="ck_pasos_paso",
        ),
        {"schema": "radar"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    imagen_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
        # La FK con ON DELETE SET NULL se configura en la migración Alembic
    )
    paso: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    exitoso: Mapped[bool] = mapped_column(Boolean, default=True)
    mensaje_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ejecutado_en: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    def __repr__(self) -> str:
        return f"<ProcesamentoPaso id={self.id} imagen_id={self.imagen_id} paso={self.paso}>"


class MetricaProcesamiento(Base):
    """
    Métricas de calidad del pipeline.
    Corresponde a radar.metricas_procesamiento.
    """

    __tablename__ = "metricas_procesamiento"
    __table_args__ = {"schema": "radar"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    imagen_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # ── Conteos de píxeles ───────────────────────────────────────────────────
    pixeles_originales: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pixeles_limpios: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pixeles_rellenados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pixeles_perdidos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Error porcentual ─────────────────────────────────────────────────────
    error_relleno_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0.00)

    procesado_en: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    def __repr__(self) -> str:
        return f"<MetricaProcesamiento imagen_id={self.imagen_id} error={self.error_relleno_pct}%>"


class IntentoDescarga(Base):
    """
    Registro de reintentos de descarga (Ruta B — URL DACC).
    Corresponde a radar.intentos_descarga.
    """

    __tablename__ = "intentos_descarga"
    __table_args__ = {"schema": "radar"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    exitoso: Mapped[bool] = mapped_column(Boolean, nullable=False)
    motivo_fallo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    intento_numero: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    fecha_intento: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp(), index=True
    )

    def __repr__(self) -> str:
        return f"<IntentoDescarga url={self.url} exitoso={self.exitoso}>"


class Usuario(Base):
    """
    Tabla de usuarios del sistema.
    Almacena credenciales y información de acceso de usuarios autenticados.
    """

    __tablename__ = "usuarios"
    __table_args__ = (
        CheckConstraint(
            "rol IN ('admin', 'operador', 'visualizador')",
            name="ck_usuarios_rol",
        ),
        UniqueConstraint("username", name="uq_usuarios_username"),
        UniqueConstraint("email", name="uq_usuarios_email"),
        {"schema": "radar"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    email: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    rol: Mapped[RolUsuario] = mapped_column(
    SQLEnum(RolUsuario, name="enum_rol_usuario", values_callable=lambda x: [e.value for e in x]),
    nullable=False,
    default=RolUsuario.VISUALIZADOR,
)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    ultimo_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    def __repr__(self) -> str:
        return f"<Usuario username={self.username} rol={self.rol} activo={self.activo}>"