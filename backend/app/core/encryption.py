from base64 import urlsafe_b64decode
from dataclasses import dataclass
from os import urandom

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

NONCE_BYTES = 12


@dataclass(frozen=True, slots=True)
class EncryptedValue:
    ciphertext: bytes
    nonce: bytes


class SecretBox:
    def __init__(self, encoded_key: str = settings.data_encryption_key) -> None:
        key = urlsafe_b64decode(encoded_key.encode())
        if len(key) != 32:
            raise ValueError("FLOWTEST_DATA_ENCRYPTION_KEY must decode to exactly 32 bytes")
        self._cipher = AESGCM(key)

    def encrypt(self, value: str, *, associated_data: bytes) -> EncryptedValue:
        nonce = urandom(NONCE_BYTES)
        ciphertext = self._cipher.encrypt(nonce, value.encode(), associated_data)
        return EncryptedValue(ciphertext=ciphertext, nonce=nonce)

    def decrypt(self, value: EncryptedValue, *, associated_data: bytes) -> str:
        plaintext = self._cipher.decrypt(value.nonce, value.ciphertext, associated_data)
        return plaintext.decode()


secret_box = SecretBox()
