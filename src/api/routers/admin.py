# src/api/routers/admin.py
"""
Router de administración: gestión de usuarios y configuración del sistema.

Solo accesible por rol 'admin'.

Endpoints:
- GET    /admin/usuarios              → Listar usuarios
- POST   /admin/usuarios              → Crear usuario
- GET    /admin/usuarios/{id}         → Detalle de usuario
- PATCH  /admin/usuarios/{id}/rol     → Cambiar rol
- PATCH  /admin/usuarios/{id}/estado  → Activar/desactivar
- DELETE /admin/usuarios/{id}         → Eliminar usuario
- GET    /admin/intentos-descarga     → Historial de descargas URL
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_db, require_role
from src.api.schemas.usuario import (
    CrearUsuarioRequest,
    CambiarRolRequest,
    CambiarEstadoRequest,
    UsuarioResponse,
    UsuarioListaResponse,
)
from src.auth.security import hash_password
from src.db.models import RolUsuario
from src.db.repository import UsuarioRepository, IntentoDescargaRepository

router = APIRouter(prefix="/admin", tags=["administración"])


@router.get(
    "/usuarios",
    response_model=UsuarioListaResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def listar_usuarios(
    activo: bool | None = Query(default=None, description="Filtrar por estado activo"),
    rol: str | None = Query(default=None, description="Filtrar por rol"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> UsuarioListaResponse:
    """Lista todos los usuarios del sistema con filtros opcionales."""
    repo = UsuarioRepository(db)
    rol_enum = RolUsuario(rol) if rol else None
    usuarios = await repo.listar(activo=activo, rol=rol_enum, limit=limit, offset=offset)
    return UsuarioListaResponse(
        total=len(usuarios),
        limit=limit,
        offset=offset,
        items=[UsuarioResponse.model_validate(u) for u in usuarios],
    )


@router.post(
    "/usuarios",
    response_model=UsuarioResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("admin"))],
)
async def crear_usuario(
    request: CrearUsuarioRequest,
    db: AsyncSession = Depends(get_db),
) -> UsuarioResponse:
    """
    Crea un nuevo usuario en el sistema.

    La contraseña se hashea con bcrypt antes de persistir.
    El username y email deben ser únicos.
    """
    repo = UsuarioRepository(db)

    # Verificar unicidad
    if await repo.obtener_por_username(request.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El username '{request.username}' ya está en uso.",
        )
    if await repo.obtener_por_email(request.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El email '{request.email}' ya está en uso.",
        )

    password_hash = hash_password(request.password)
    rol_enum = RolUsuario(request.rol)

    usuario = await repo.crear(
        username=request.username,
        email=request.email,
        password_hash=password_hash,
        rol=rol_enum,
    )
    return UsuarioResponse.model_validate(usuario)


@router.get(
    "/usuarios/{usuario_id}",
    response_model=UsuarioResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def obtener_usuario(
    usuario_id: int,
    db: AsyncSession = Depends(get_db),
) -> UsuarioResponse:
    """Devuelve el detalle de un usuario por su ID."""
    repo = UsuarioRepository(db)
    usuario = await repo.obtener_por_id(usuario_id)
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado.",
        )
    return UsuarioResponse.model_validate(usuario)


@router.patch(
    "/usuarios/{usuario_id}/rol",
    response_model=UsuarioResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def cambiar_rol(
    usuario_id: int,
    request: CambiarRolRequest,
    db: AsyncSession = Depends(get_db),
) -> UsuarioResponse:
    """Cambia el rol de un usuario."""
    repo = UsuarioRepository(db)
    usuario = await repo.obtener_por_id(usuario_id)
    if usuario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")

    await repo.cambiar_rol(usuario_id, RolUsuario(request.rol))
    usuario = await repo.obtener_por_id(usuario_id)
    return UsuarioResponse.model_validate(usuario)


@router.patch(
    "/usuarios/{usuario_id}/estado",
    response_model=UsuarioResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def cambiar_estado(
    usuario_id: int,
    request: CambiarEstadoRequest,
    db: AsyncSession = Depends(get_db),
) -> UsuarioResponse:
    """Activa o desactiva un usuario."""
    repo = UsuarioRepository(db)
    usuario = await repo.obtener_por_id(usuario_id)
    if usuario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")

    await repo.cambiar_estado(usuario_id, request.activo)
    usuario = await repo.obtener_por_id(usuario_id)
    return UsuarioResponse.model_validate(usuario)


@router.delete(
    "/usuarios/{usuario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role("admin"))],
)
async def eliminar_usuario(
    usuario_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> None:
    """
    Elimina un usuario del sistema.

    No se puede eliminar el propio usuario autenticado.
    """
    if int(current_user["sub"]) == usuario_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No podés eliminar tu propio usuario.",
        )

    repo = UsuarioRepository(db)
    usuario = await repo.obtener_por_id(usuario_id)
    if usuario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")

    await repo.eliminar(usuario_id)


@router.get(
    "/intentos-descarga",
    dependencies=[Depends(require_role("admin", "operador"))],
)
async def listar_intentos_descarga(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """
    Devuelve el historial reciente de intentos de descarga desde la URL DACC.

    Incluye tanto los exitosos como los fallidos con motivo de error.
    """
    repo = IntentoDescargaRepository(db)
    intentos = await repo.listar_recientes(limit=limit)
    return [
        {
            "id": i.id,
            "url": i.url,
            "exitoso": i.exitoso,
            "motivo_fallo": i.motivo_fallo,
            "intento_numero": i.intento_numero,
            "fecha_intento": i.fecha_intento,
        }
        for i in intentos
    ]