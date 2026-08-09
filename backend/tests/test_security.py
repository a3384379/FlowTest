from uuid import uuid4

import jwt

from app.core.security import PasswordService, TokenService


def test_password_hash_is_argon2_and_verifies() -> None:
    service = PasswordService()
    password_hash = service.hash("a-secure-password")

    assert password_hash.startswith("$argon2id$")
    assert service.verify(password_hash, "a-secure-password")
    assert not service.verify(password_hash, "wrong-password")
    assert not service.verify("not-a-password-hash", "a-secure-password")


def test_access_token_round_trip_and_refresh_digest() -> None:
    service = TokenService()
    user_id = uuid4()

    token = service.create_access_token(user_id)
    claims = service.decode_access_token(token)
    refresh_token = service.create_refresh_token()

    assert claims.user_id == user_id
    assert len(refresh_token) >= 64
    assert service.digest_refresh_token(refresh_token) == service.digest_refresh_token(
        refresh_token
    )


def test_access_decoder_rejects_wrong_token_type() -> None:
    from app.core.config import settings

    token = jwt.encode({"type": "refresh"}, settings.secret_key, algorithm="HS256")

    try:
        TokenService().decode_access_token(token)
    except jwt.InvalidTokenError:
        pass
    else:
        raise AssertionError("A refresh token must not be accepted as an access token")
