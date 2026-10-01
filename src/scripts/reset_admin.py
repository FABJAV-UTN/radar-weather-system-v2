# src/scripts/reset_admin.py
"""
Resetea (o crea) el usuario administrador del sistema.

Pensado para las máquinas del laboratorio: cada una tiene su propia base
PostgreSQL en Docker, así que la contraseña del admin puede no coincidir
entre equipos. Este script deja el admin con una contraseña conocida sin
tocar el resto de los datos.

Uso (dentro del contenedor backend):

    docker compose exec backend \\
        uv run --no-dev python -m src.scripts.reset_admin

    # con valores explícitos
    docker compose exec backend \\
        uv run --no-dev python -m src.scripts.reset_admin \\
        --username admin --password "miClaveSegura" --email admin@admin.com

Sin argumentos deja admin / admin (uso de laboratorio). Con --aleatoria
genera una contraseña de 12 caracteres y la imprime una sola vez.
"""
from __future__ import annotations

import argparse
import asyncio
import secrets
import string

from sqlalchemy import select

from src.auth.security import hash_password
from src.db.connection import AsyncSessionLocal
from src.db.models import RolUsuario, Usuario

# La API exige un mínimo de 8 caracteres (ver src/api/schemas/usuario.py).
MIN_PASSWORD_LEN = 8


def _generar_password(longitud: int = 12) -> str:
    """Genera una contraseña aleatoria legible (letras + dígitos)."""
    alfabeto = string.ascii_letters + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(longitud))


async def reset_admin(username: str, password: str, email: str) -> bool:
    """
    Crea el admin si no existe, o le resetea la contraseña si ya existe.

    Returns:
        True si se creó un usuario nuevo, False si se actualizó uno existente.
    """
    async with AsyncSessionLocal() as session:
        resultado = await session.execute(
            select(Usuario).where(Usuario.username == username)
        )
        usuario = resultado.scalar_one_or_none()

        creado = usuario is None
        if usuario is None:
            usuario = Usuario(
                username=username,
                email=email,
                password_hash=hash_password(password),
                rol=RolUsuario.ADMIN,
                activo=True,
            )
            session.add(usuario)
        else:
            usuario.password_hash = hash_password(password)
            usuario.rol = RolUsuario.ADMIN
            usuario.activo = True

        await session.commit()
        return creado


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resetea o crea el usuario administrador."
    )
    parser.add_argument("--username", default="admin", help="Usuario (default: admin)")
    parser.add_argument(
        "--email", default="admin@admin.com", help="Email (default: admin@admin.com)"
    )
    parser.add_argument(
        "--password",
        default="admin",
        help="Contraseña nueva (default: admin). Con --aleatoria se genera una.",
    )
    parser.add_argument(
        "--aleatoria", action="store_true", help="Generar una contraseña aleatoria de 12 caracteres."
    )
    args = parser.parse_args()

    password = _generar_password() if args.aleatoria else args.password
    if len(password) < MIN_PASSWORD_LEN:
        print(f"⚠ Contraseña de menos de {MIN_PASSWORD_LEN} caracteres: solo para uso en el laboratorio.")

    creado = asyncio.run(reset_admin(args.username, password, args.email))

    accion = "creado" if creado else "actualizado"
    print(f"✓ Usuario admin '{args.username}' {accion}.")
    print(f"  usuario:     {args.username}")
    print(f"  contraseña:  {password}")
    if args.aleatoria:
        print("  (guardala: no se vuelve a mostrar)")


if __name__ == "__main__":
    main()
