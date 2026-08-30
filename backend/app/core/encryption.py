from base64 import urlsafe_b64decode
from binascii import Error as BinasciiError
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from os import urandom

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

NONCE_BYTES = 12
DEFAULT_KEY_REFERENCE = "settings:data_encryption_key"
_ENVELOPE_MAGIC = b"FTK1"
_REFERENCE_LENGTH_BYTES = 2


@dataclass(frozen=True, slots=True)
class EncryptedValue:
    ciphertext: bytes
    nonce: bytes


class SecretBox:
    def __init__(
        self,
        encoded_key: str = settings.data_encryption_key,
        *,
        keyring: Mapping[str, str] | None = None,
    ) -> None:
        self._encoded_key = encoded_key
        self._keyring = dict(keyring) if keyring is not None else None
        self._ciphers: dict[str, AESGCM] = {DEFAULT_KEY_REFERENCE: AESGCM(_decode_key(encoded_key))}

    def has_reference(self, key_reference: str) -> bool:
        try:
            self._encoded_key_for_reference(key_reference)
        except ValueError:
            return False
        return True

    def fingerprint(self, key_reference: str) -> str:
        encoded_key = self._encoded_key_for_reference(key_reference)
        return sha256(encoded_key.encode()).hexdigest()

    def encrypt(
        self,
        value: str,
        *,
        associated_data: bytes,
        key_reference: str = DEFAULT_KEY_REFERENCE,
    ) -> EncryptedValue:
        encoded_reference = _encode_reference(key_reference)
        cipher = self._cipher(key_reference)
        authenticated_data = _keyed_associated_data(associated_data, encoded_reference)
        nonce = urandom(NONCE_BYTES)
        ciphertext = cipher.encrypt(nonce, value.encode(), authenticated_data)
        envelope = (
            _ENVELOPE_MAGIC
            + len(encoded_reference).to_bytes(_REFERENCE_LENGTH_BYTES, "big")
            + encoded_reference
            + ciphertext
        )
        return EncryptedValue(ciphertext=envelope, nonce=nonce)

    def decrypt(self, value: EncryptedValue, *, associated_data: bytes) -> str:
        key_reference, ciphertext = _unwrap_ciphertext(value.ciphertext)
        if key_reference is None:
            cipher = self._cipher(DEFAULT_KEY_REFERENCE)
            plaintext = cipher.decrypt(value.nonce, ciphertext, associated_data)
            return plaintext.decode()
        encoded_reference = _encode_reference(key_reference)
        cipher = self._cipher(key_reference)
        plaintext = cipher.decrypt(
            value.nonce,
            ciphertext,
            _keyed_associated_data(associated_data, encoded_reference),
        )
        return plaintext.decode()

    def reference(self, ciphertext: bytes) -> str:
        key_reference, _payload = _unwrap_ciphertext(ciphertext)
        return key_reference or DEFAULT_KEY_REFERENCE

    def _cipher(self, key_reference: str) -> AESGCM:
        cipher = self._ciphers.get(key_reference)
        if cipher is not None:
            return cipher
        cipher = AESGCM(_decode_key(self._encoded_key_for_reference(key_reference)))
        self._ciphers[key_reference] = cipher
        return cipher

    def _encoded_key_for_reference(self, key_reference: str) -> str:
        if key_reference == DEFAULT_KEY_REFERENCE:
            return self._encoded_key
        keyring = self._keyring if self._keyring is not None else settings.data_encryption_keyring
        encoded_key = keyring.get(key_reference)
        if encoded_key is None:
            raise ValueError(f"Data encryption key reference is unavailable: {key_reference}")
        _decode_key(encoded_key)
        return encoded_key


def _decode_key(encoded_key: str) -> bytes:
    try:
        key = urlsafe_b64decode(encoded_key.encode())
    except (BinasciiError, ValueError) as error:
        raise ValueError("Data encryption keys must use URL-safe base64") from error
    if len(key) != 32:
        raise ValueError("FLOWTEST_DATA_ENCRYPTION_KEY must decode to exactly 32 bytes")
    return key


def _encode_reference(key_reference: str) -> bytes:
    encoded = key_reference.encode()
    if not encoded or len(encoded) > 200:
        raise ValueError("Data encryption key references must be 1-200 UTF-8 bytes")
    return encoded


def _keyed_associated_data(associated_data: bytes, encoded_reference: bytes) -> bytes:
    return associated_data + b"\x00flowtest-key-reference:" + encoded_reference


def _unwrap_ciphertext(ciphertext: bytes) -> tuple[str | None, bytes]:
    if not ciphertext.startswith(_ENVELOPE_MAGIC):
        return None, ciphertext
    prefix_length = len(_ENVELOPE_MAGIC) + _REFERENCE_LENGTH_BYTES
    if len(ciphertext) <= prefix_length:
        raise ValueError("Encrypted value key envelope is truncated")
    reference_length = int.from_bytes(
        ciphertext[len(_ENVELOPE_MAGIC) : prefix_length],
        "big",
    )
    reference_end = prefix_length + reference_length
    if reference_length == 0 or reference_length > 200 or len(ciphertext) <= reference_end:
        raise ValueError("Encrypted value key envelope is invalid")
    try:
        key_reference = ciphertext[prefix_length:reference_end].decode()
    except UnicodeDecodeError as error:
        raise ValueError("Encrypted value key reference is invalid") from error
    return key_reference, ciphertext[reference_end:]


secret_box = SecretBox()
