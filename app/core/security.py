from datetime import datetime, timedelta, timezone
from typing import Any, Union, Optional
from jose import jwt, JWTError
import bcrypt
from app.core.config import settings

# JWT Configuration constants
ALGORITHM = "HS256"

def hash_password(password: str) -> str:
    """
    Hash a plain-text password using the bcrypt algorithm directly.
    """
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain-text password against a stored bcrypt hash directly.
    """
    plain_bytes = plain_password.encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")
    try:
        return bcrypt.checkpw(plain_bytes, hashed_bytes)
    except Exception:
        return False

def create_access_token(subject: Union[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Generate a short-lived JWT access token.
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {"exp": expire, "sub": str(subject), "type": "access"}
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_refresh_token(subject: Union[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Generate a longer-lived JWT refresh token.
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=7)  # Refresh token defaults to 7 days
    
    to_encode = {"exp": expire, "sub": str(subject), "type": "refresh"}
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_token(token: str) -> dict:
    """
    Decode and validate a JWT token.
    Raises jose.JWTError if the token is invalid or expired.
    """
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])

import os
import base64
import hashlib
from cryptography.fernet import Fernet

def get_encryption_key() -> bytes:
    """
    Get or derive a 32-byte base64 URL-safe key for Fernet encryption.
    """
    custom_key = os.getenv("DATABASE_ENCRYPTION_KEY")
    if custom_key:
        try:
            key_bytes = base64.urlsafe_b64decode(custom_key)
            if len(key_bytes) == 32:
                return custom_key.encode()
        except Exception:
            pass
        raw_key = custom_key.encode()
    else:
        raw_key = settings.JWT_SECRET_KEY.encode()
        
    hashed = hashlib.sha256(raw_key).digest()
    return base64.urlsafe_b64encode(hashed)

def encrypt_string(plain_text: Optional[str]) -> Optional[str]:
    """
    Encrypt a sensitive string.
    """
    if not plain_text:
        return plain_text
    f = Fernet(get_encryption_key())
    return f.encrypt(plain_text.encode()).decode()

def decrypt_string(encrypted_text: Optional[str]) -> Optional[str]:
    """
    Decrypt an encrypted string.
    """
    if not encrypted_text:
        return encrypted_text
    try:
        f = Fernet(get_encryption_key())
        return f.decrypt(encrypted_text.encode()).decode()
    except Exception:
        # Fallback to returning the raw text if decryption fails
        return encrypted_text
