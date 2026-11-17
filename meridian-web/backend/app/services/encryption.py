"""API key encryption/decryption using Fernet."""

import logging

from cryptography.fernet import Fernet

from ..config import get_settings

logger = logging.getLogger(__name__)

_fernet = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        settings = get_settings()
        key = settings.encryption_key
        if not key:
            # Generate and warn; in production this must be set
            key = Fernet.generate_key().decode()
            logger.warning(
                "ENCRYPTION_KEY не задан, сгенерирован временный ключ. "
                "Задайте ENCRYPTION_KEY для постоянного шифрования API-ключей."
            )
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt_api_key(plain_key: str) -> str:
    return _get_fernet().encrypt(plain_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    return _get_fernet().decrypt(encrypted_key.encode()).decode()


def mask_api_key(plain_key: str) -> str:
    """Show first 4 and last 4 chars, mask the rest."""
    if len(plain_key) <= 8:
        return "****"
    return plain_key[:4] + "****" + plain_key[-4:]
