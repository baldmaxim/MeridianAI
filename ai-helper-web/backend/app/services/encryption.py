"""API key encryption/decryption using Fernet."""

from cryptography.fernet import Fernet

from ..config import get_settings

_fernet = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        settings = get_settings()
        key = settings.encryption_key
        if not key:
            # Generate and warn; in production this must be set
            key = Fernet.generate_key().decode()
            print(f"WARNING: No ENCRYPTION_KEY set. Generated temporary key: {key}")
            print("Set ENCRYPTION_KEY in .env for persistent API key encryption.")
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
