"""Public auth endpoints — no Bearer token required."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth import (
    AuthRole,
    AuthenticatedUser,
    authenticate_user,
    create_access_token,
    require_auth,
)

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: AuthRole
    display_name: str
    patient_id: str | None = None
    doctor_id: str | None = None
    family_member_id: str | None = None


@auth_router.post("/login", response_model=TokenResponse)
async def login(request: Request) -> TokenResponse:
    form = await request.form()
    username = str(form.get("username", ""))
    password = str(form.get("password", ""))
    user = authenticate_user(username, password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(
        access_token=create_access_token(
            user.username,
            role=user.role,
            display_name=user.display_name,
            patient_id=user.patient_id,
            doctor_id=user.doctor_id,
            family_member_id=user.family_member_id,
        ),
        username=user.username,
        role=user.role,
        display_name=user.display_name,
        patient_id=user.patient_id,
        doctor_id=user.doctor_id,
        family_member_id=user.family_member_id,
    )


@auth_router.get("/me", response_model=AuthenticatedUser)
async def me(user: AuthenticatedUser = Depends(require_auth)) -> AuthenticatedUser:
    return user
