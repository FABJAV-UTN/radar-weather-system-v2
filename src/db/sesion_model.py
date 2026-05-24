# src/db/sesion_model.py
"""
Modelo SQLAlchemy para radar.sesiones.
Separado para evitar importación circular con models.py principal.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models import Base


class Sesion(Base):
    """
    Tabla de sesiones JWT activas para auditabilidad.
    Corresponde a radar.sesiones.
    """

    __tablename__ = "sesiones"
    __table_args__ = {"schema": "radar"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usuario_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    refresh_token: Mapped[str] = mapped_column(String(512), nullable=False, unique=True, index=True)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    revocada_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<Sesion usuario_id={self.usuario_id} activa={self.activa}>"