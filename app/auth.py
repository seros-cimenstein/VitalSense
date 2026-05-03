"""JWT authentication helpers for VitalSense.

Role logins are controlled by env vars:
  VITALSENSE_ADMIN_USER / VITALSENSE_ADMIN_HASH       (default: admin/admin)
  VITALSENSE_PATIENT_USER / VITALSENSE_PATIENT_HASH   (default: patient/patient)
  VITALSENSE_DOCTOR_USER / VITALSENSE_DOCTOR_HASH     (default: doctor/doctor)
  VITALSENSE_RELATIVE_USER / VITALSENSE_RELATIVE_HASH (default: relative/relative)
  VITALSENSE_SECRET_KEY                               (MUST be set in production)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

SECRET_KEY = os.getenv("VITALSENSE_SECRET_KEY", "vitalsense-dev-secret-change-in-prod")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 8 * 60

_pwd = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

DEMO_PATIENT_ID = "demo-patient"
DEMO_DOCTOR_ID = "demo-doctor"
DEMO_FAMILY_ID = "demo-relative"

ADMIN_USERNAME = os.getenv("VITALSENSE_ADMIN_USER", "admin")
ADMIN_PASSWORD_HASH = os.getenv("VITALSENSE_ADMIN_HASH") or _pwd.hash("admin")
PATIENT_USERNAME = os.getenv("VITALSENSE_PATIENT_USER", "patient")
PATIENT_PASSWORD_HASH = os.getenv("VITALSENSE_PATIENT_HASH") or _pwd.hash("patient")
DOCTOR_USERNAME = os.getenv("VITALSENSE_DOCTOR_USER", "doctor")
DOCTOR_PASSWORD_HASH = os.getenv("VITALSENSE_DOCTOR_HASH") or _pwd.hash("doctor")
RELATIVE_USERNAME = os.getenv("VITALSENSE_RELATIVE_USER", "relative")
RELATIVE_PASSWORD_HASH = os.getenv("VITALSENSE_RELATIVE_HASH") or _pwd.hash("relative")
FAMILY_USERNAME = os.getenv("VITALSENSE_FAMILY_USER", "family")
FAMILY_PASSWORD_HASH = os.getenv("VITALSENSE_FAMILY_HASH") or _pwd.hash("family")


class AuthRole(str, Enum):
    ADMIN = "admin"
    PATIENT = "patient"
    DOCTOR = "doctor"
    FAMILY = "family"


class AuthenticatedUser(BaseModel):
    username: str
    role: AuthRole
    display_name: str
    patient_id: Optional[str] = None
    doctor_id: Optional[str] = None
    family_member_id: Optional[str] = None


@dataclass(frozen=True)
class AuthAccount:
    username: str
    password_hash: str
    principal: AuthenticatedUser


def configured_accounts() -> list[AuthAccount]:
    return [
        AuthAccount(
            username=ADMIN_USERNAME,
            password_hash=ADMIN_PASSWORD_HASH,
            principal=AuthenticatedUser(
                username=ADMIN_USERNAME,
                role=AuthRole.ADMIN,
                display_name="Admin",
            ),
        ),
        AuthAccount(
            username=PATIENT_USERNAME,
            password_hash=PATIENT_PASSWORD_HASH,
            principal=AuthenticatedUser(
                username=PATIENT_USERNAME,
                role=AuthRole.PATIENT,
                display_name="Ahmet Yilmaz",
                patient_id=DEMO_PATIENT_ID,
            ),
        ),
        AuthAccount(
            username=DOCTOR_USERNAME,
            password_hash=DOCTOR_PASSWORD_HASH,
            principal=AuthenticatedUser(
                username=DOCTOR_USERNAME,
                role=AuthRole.DOCTOR,
                display_name="Dr. Elif Demir",
                doctor_id=DEMO_DOCTOR_ID,
            ),
        ),
        AuthAccount(
            username=RELATIVE_USERNAME,
            password_hash=RELATIVE_PASSWORD_HASH,
            principal=AuthenticatedUser(
                username=RELATIVE_USERNAME,
                role=AuthRole.FAMILY,
                display_name="Mina Yilmaz",
                patient_id=DEMO_PATIENT_ID,
                family_member_id=DEMO_FAMILY_ID,
            ),
        ),
        AuthAccount(
            username=FAMILY_USERNAME,
            password_hash=FAMILY_PASSWORD_HASH,
            principal=AuthenticatedUser(
                username=FAMILY_USERNAME,
                role=AuthRole.FAMILY,
                display_name="Mina Yilmaz",
                patient_id=DEMO_PATIENT_ID,
                family_member_id=DEMO_FAMILY_ID,
            ),
        ),
    ]


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


def authenticate_user(username: str, password: str) -> Optional[AuthenticatedUser]:
    for account in configured_accounts():
        if account.username == username and verify_password(password, account.password_hash):
            return account.principal
    return None


def create_access_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
    role: AuthRole | str | None = None,
    display_name: Optional[str] = None,
    patient_id: Optional[str] = None,
    doctor_id: Optional[str] = None,
    family_member_id: Optional[str] = None,
) -> str:
    if role is None:
        account = next((a for a in configured_accounts() if a.username == subject), None)
        if account is not None:
            role = account.principal.role
            display_name = account.principal.display_name
            patient_id = account.principal.patient_id
            doctor_id = account.principal.doctor_id
            family_member_id = account.principal.family_member_id
        else:
            role = AuthRole.ADMIN

    auth_role = role if isinstance(role, AuthRole) else AuthRole(str(role))
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": subject,
        "role": auth_role.value,
        "display_name": display_name or subject,
        "patient_id": patient_id,
        "doctor_id": doctor_id,
        "family_member_id": family_member_id,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


async def require_auth(token: str = Depends(oauth2_scheme)) -> AuthenticatedUser:
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
        role = AuthRole(payload.get("role", AuthRole.ADMIN.value))
        return AuthenticatedUser(
            username=sub,
            role=role,
            display_name=payload.get("display_name") or sub,
            patient_id=payload.get("patient_id"),
            doctor_id=payload.get("doctor_id"),
            family_member_id=payload.get("family_member_id"),
        )
    except (JWTError, ValueError):
        raise exc


def require_roles(*roles: AuthRole):
    async def _require_role(user: AuthenticatedUser = Depends(require_auth)) -> AuthenticatedUser:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role for this action",
            )
        return user

    return _require_role
