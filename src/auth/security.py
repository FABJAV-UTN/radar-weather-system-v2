# src/auth/security.py
"""
Utilidades de seguridad: hash y verificación de contraseñas con bcrypt.
"""
import bcrypt


def hash_password(plain_password: str) -> str:
    """
    Genera un hash bcrypt de la contraseña en texto plano.

    Args:
        plain_password: Contraseña en texto plano.

    Returns:
        Hash bcrypt como string UTF-8.
    """
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica si una contraseña en texto plano coincide con su hash bcrypt.

    Args:
        plain_password: Contraseña a verificar.
        hashed_password: Hash almacenado en base de datos.

    Returns:
        True si la contraseña es correcta.
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )