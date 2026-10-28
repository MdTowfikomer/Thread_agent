"""AES-256-GCM secret envelopes bound to their organization and purpose.

Wire format: base64(12-byte random nonce || ciphertext || 16-byte GCM tag).
The master key is never persisted. Python strings cannot promise memory zeroization.
"""
import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException


class SecretConfigurationError(HTTPException):
    def __init__(self):
        super().__init__(503, "Credential encryption is unavailable. Ask the operator to check THREAD_MASTER_ENCRYPTION_KEY.")


def _cipher():
    raw_key = os.environ.get("THREAD_MASTER_ENCRYPTION_KEY", "").strip()
    try:
        # Support both standard base64 and urlsafe base64 (- -> +, _ -> /)
        normalized = raw_key.replace("-", "+").replace("_", "/")
        padding = len(normalized) % 4
        if padding:
            normalized += "=" * (4 - padding)
        key = base64.b64decode(normalized, validate=True)
    except (ValueError, binascii.Error):
        raise SecretConfigurationError() from None
    if len(key) != 32:
        raise SecretConfigurationError()
    return AESGCM(key)


def encrypt_secret(plaintext: str, *, associated_data: str) -> str:
    cipher = _cipher()
    nonce = os.urandom(12)
    return base64.b64encode(nonce + cipher.encrypt(nonce, plaintext.encode(), associated_data.encode())).decode()


def decrypt_secret(envelope: str, *, associated_data: str) -> str:
    cipher = _cipher()
    try:
        raw = base64.b64decode(envelope, validate=True)
        if len(raw) < 29:
            raise ValueError()
        return cipher.decrypt(raw[:12], raw[12:], associated_data.encode()).decode()
    except (InvalidTag, ValueError, UnicodeError, binascii.Error, TypeError):
        raise HTTPException(503, "The saved credential cannot be decrypted. Check the encryption key or reconnect the model provider.") from None
