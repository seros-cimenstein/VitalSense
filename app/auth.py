"""JWT authentication helpers for VitalSense.

Single-admin auth controlled by env vars:
  VITALSENSE_ADMIN_USER   — username (default: admin)
  VITALSENSE_ADMIN_HASH   — bcrypt hash of password (default: hash of "admin")
  VITALSENSE_SECRET_KEY   — signing secret (MUST be set in production)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

SECRET_KEY = os.getenv("VITALSENSE_SECRET_KEY", "vitalsense-dev-secret-change-in-prod")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 8 * 60

_pwd = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

ADMIN_USERNAME = os.getenv("VITALSENSE_ADMIN_USER", "admin")
ADMIN_PASSWORD_HASH = os.getenv("VITALSENSE_ADMIN_HASH") or _pwd.hash("admin")


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return jwt.encode({"sub": subject, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def require_auth(token: str = Depends(oauth2_scheme)) -> str:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub: Optional[str] = payload.get("sub")
        if sub is None:
            raise exc
        return sub
    except JWTError:
        raise exc
