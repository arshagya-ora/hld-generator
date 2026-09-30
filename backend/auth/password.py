"""
Password hashing utilities.

Uses bcrypt_sha256 for new hashes so long passwords do not fail on bcrypt's
72-byte input limit, while still accepting legacy bcrypt hashes.
"""
from passlib.context import CryptContext

# Prefer bcrypt_sha256 for new hashes but keep bcrypt enabled for legacy users.
pwd_context = CryptContext(
    schemes=["bcrypt_sha256", "bcrypt"],
    deprecated="auto",
    default="bcrypt_sha256",
    bcrypt_sha256__rounds=12,
    bcrypt__rounds=12  # Cost factor for bcrypt (higher = more secure, slower)
)


def hash_password(password: str) -> str:
    """
    Hash a plain text password using bcrypt

    Args:
        password: Plain text password

    Returns:
        Hashed password string
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain text password against a hashed password

    Args:
        plain_password: Plain text password to verify
        hashed_password: Hashed password from database

    Returns:
        True if password matches, False otherwise
    """
    return pwd_context.verify(plain_password, hashed_password)


def validate_password_complexity(password: str) -> tuple[bool, str]:
    """
    Validate password complexity requirements

    Requirements:
    - At least 12 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character

    Args:
        password: Password to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(password) < 12:
        return False, "Password must be at least 12 characters long"

    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"

    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"

    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one digit"

    special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?"
    if not any(c in special_chars for c in password):
        return False, "Password must contain at least one special character"

    return True, ""
