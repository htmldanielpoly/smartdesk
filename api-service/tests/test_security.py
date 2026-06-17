"""Unit tests for password hashing and JWT handling. No DB or network."""
import jwt
import pytest

from app.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_round_trip():
    h = hash_password("s3cret-password")
    assert h != "s3cret-password"  # never stored in plain text
    assert verify_password("s3cret-password", h) is True
    assert verify_password("wrong-password", h) is False


def test_token_round_trip():
    token = create_access_token("507f1f77bcf86cd799439011", "AGENT")
    payload = decode_access_token(token)
    assert payload["sub"] == "507f1f77bcf86cd799439011"
    assert payload["role"] == "AGENT"


def test_tampered_token_rejected():
    token = create_access_token("abc", "USER")
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(token + "tampered")
