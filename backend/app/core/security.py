from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Any
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import settings

ALGORITHM = "HS256"


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: UUID
    token_id: UUID
    expires_at: datetime


class PasswordService:
    def __init__(self) -> None:
        self._hasher = PasswordHasher()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (InvalidHashError, VerificationError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        return self._hasher.check_needs_rehash(password_hash)


class TokenService:
    def create_access_token(self, user_id: UUID) -> str:
        issued_at = datetime.now(UTC)
        expires_at = issued_at + timedelta(minutes=settings.access_token_minutes)
        payload = {
            "sub": str(user_id),
            "jti": str(uuid4()),
            "type": "access",
            "iat": issued_at,
            "exp": expires_at,
        }
        return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        payload: dict[str, Any] = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise jwt.InvalidTokenError("Unexpected token type")
        expires_at = datetime.fromtimestamp(float(payload["exp"]), tz=UTC)
        return AccessTokenClaims(
            user_id=UUID(str(payload["sub"])),
            token_id=UUID(str(payload["jti"])),
            expires_at=expires_at,
        )

    def create_refresh_token(self) -> str:
        return token_urlsafe(48)

    @staticmethod
    def digest_refresh_token(token: str) -> str:
        return sha256(token.encode()).hexdigest()


password_service = PasswordService()
token_service = TokenService()
