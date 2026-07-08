import pytest
from datetime import timedelta
from jose import jwt, JWTError

from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token, ALGORITHM
from app.core.config import settings

def test_password_hashing():
    password = "MySecurePassword123"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("wrongpassword", hashed) is False

def test_access_token_creation_and_decoding():
    subject = "user123"
    token = create_access_token(subject=subject)
    assert isinstance(token, str)
    
    payload = decode_token(token)
    assert payload["sub"] == subject
    assert payload["type"] == "access"
    assert "exp" in payload

def test_refresh_token_creation_and_decoding():
    subject = "user456"
    token = create_refresh_token(subject=subject)
    assert isinstance(token, str)
    
    payload = decode_token(token)
    assert payload["sub"] == subject
    assert payload["type"] == "refresh"
    assert "exp" in payload

def test_expired_token():
    subject = "expired_user"
    # Create token that expired 10 minutes ago
    delta = timedelta(minutes=-10)
    token = create_access_token(subject=subject, expires_delta=delta)
    
    with pytest.raises(JWTError):
        decode_token(token)

def test_invalid_token():
    with pytest.raises(JWTError):
        decode_token("this.is.an.invalid.token")
