"""Encryption utilities for securing private keys."""

import os
import base64
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


# Default encryption key from environment or generate one
_ENCRYPTION_KEY: Optional[bytes] = None


def _get_encryption_key() -> bytes:
    """Get or create encryption key."""
    global _ENCRYPTION_KEY
    
    if _ENCRYPTION_KEY is not None:
        return _ENCRYPTION_KEY
    
    # Try to get from environment
    key_str = os.getenv("WALLET_ENCRYPTION_KEY")
    
    if key_str:
        # Use provided key
        _ENCRYPTION_KEY = key_str.encode()
    else:
        # Generate key from a master password (should be set in production!)
        master_password = os.getenv("MASTER_PASSWORD", "funding-bot-default-key-change-me!")
        salt = os.getenv("ENCRYPTION_SALT", "funding-bot-salt").encode()
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        _ENCRYPTION_KEY = base64.urlsafe_b64encode(
            kdf.derive(master_password.encode())
        )
    
    return _ENCRYPTION_KEY


def encrypt_private_key(private_key: str) -> str:
    """
    Encrypt a private key for storage.
    
    Args:
        private_key: The private key to encrypt
        
    Returns:
        Base64-encoded encrypted private key
    """
    key = _get_encryption_key()
    fernet = Fernet(key)
    encrypted = fernet.encrypt(private_key.encode())
    return base64.urlsafe_b64encode(encrypted).decode()


def decrypt_private_key(encrypted_key: str) -> str:
    """
    Decrypt a stored private key.
    
    Args:
        encrypted_key: Base64-encoded encrypted private key
        
    Returns:
        Decrypted private key
    """
    key = _get_encryption_key()
    fernet = Fernet(key)
    encrypted_bytes = base64.urlsafe_b64decode(encrypted_key.encode())
    decrypted = fernet.decrypt(encrypted_bytes)
    return decrypted.decode()


def generate_encryption_key() -> str:
    """
    Generate a new encryption key.
    
    Use this to generate a key for production:
    python -c "from src.database.encryption import generate_encryption_key; print(generate_encryption_key())"
    
    Then set it as WALLET_ENCRYPTION_KEY environment variable.
    """
    return Fernet.generate_key().decode()

