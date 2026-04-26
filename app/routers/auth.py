from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.dependencies import get_current_user, get_face_db
from db_manager import FaceDB


router = APIRouter(prefix="/auth", tags=["认证"])
_bearer = HTTPBearer(auto_error=False)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str | None = Field(None, max_length=64)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


def _create_login_result(db: FaceDB, user: Dict[str, object]) -> Dict[str, object]:
    token_result = db.create_user_token(user_id=int(user["user_id"]), ttl_seconds=8 * 3600)
    return {
        "ok": True,
        "token_type": "bearer",
        "access_token": token_result["token"],
        "expires_at_ms": token_result["expires_at_ms"],
        "user": user,
    }


@router.post("/register", summary="注册账号")
async def register_user(
    payload: RegisterRequest,
    db: FaceDB = Depends(get_face_db),
):
    try:
        user = db.create_user(
            username=payload.username,
            password=payload.password,
            role="user",
            display_name=payload.display_name,
            is_active=True,
        )
        db.ensure_default_course_for_user(user_id=int(user["user_id"]))
        return _create_login_result(db, user)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/login", summary="账号登录")
async def login(
    payload: LoginRequest,
    db: FaceDB = Depends(get_face_db),
):
    user = db.verify_user_credentials(
        username=payload.username,
        password=payload.password,
        allowed_roles=["user", "teacher", "student", "admin"],
    )
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    db.ensure_default_course_for_user(user_id=int(user["user_id"]))
    return _create_login_result(db, user)


@router.post("/teacher/login", summary="兼容旧版教师登录")
async def teacher_login_alias(
    payload: LoginRequest,
    db: FaceDB = Depends(get_face_db),
):
    return await login(payload=payload, db=db)


@router.get("/me", summary="当前登录用户")
async def auth_me(
    user: Dict[str, object] = Depends(get_current_user),
):
    return {"ok": True, "user": user}


@router.post("/logout", summary="退出登录")
async def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: FaceDB = Depends(get_face_db),
):
    token = ""
    if credentials is not None and credentials.scheme.lower() == "bearer":
        token = str(credentials.credentials or "").strip()
    revoked = db.revoke_user_token(token) if token else False
    return {"ok": True, "revoked": revoked}
