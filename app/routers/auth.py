from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.core.settings import Settings
from app.dependencies import get_current_user, get_face_db, get_settings
from app.utils.media import to_media_url
from app.utils.uploads import persist_upload
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


class UpdateProfileRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=64)


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


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


@router.get("/profile", summary="个人主页信息")
async def get_profile(
    user: Dict[str, Any] = Depends(get_current_user),
    db: FaceDB = Depends(get_face_db),
    settings: Settings = Depends(get_settings),
):
    user_id = int(user["user_id"])
    latest_face = None
    faces = db.list_user_faces(user_id=user_id, limit=1)
    if faces:
        latest_face = dict(faces[0])
        latest_face["image_url"] = to_media_url(latest_face.get("image_path"), settings.media_root)

    face_count = db.count_user_faces(user_id=user_id)
    return {
        "ok": True,
        "profile": {
            "user_id": user_id,
            "username": user.get("username"),
            "display_name": user.get("display_name"),
            "role": user.get("role"),
            "is_active": user.get("is_active"),
            "create_time": user.get("create_time"),
            "face_count": face_count,
            "has_face": face_count > 0,
            "latest_face": latest_face,
        },
    }


@router.put("/profile", summary="修改个人昵称")
async def update_profile(
    payload: UpdateProfileRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    db: FaceDB = Depends(get_face_db),
):
    try:
        updated = db.update_user_display_name(
            user_id=int(user["user_id"]),
            display_name=payload.display_name,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "user": updated}


@router.post("/profile/face/register", summary="个人主页注册人脸")
async def register_profile_face(
    file: UploadFile = File(..., description="用户自拍照"),
    user: Dict[str, Any] = Depends(get_current_user),
    db: FaceDB = Depends(get_face_db),
    settings: Settings = Depends(get_settings),
):
    user_id = int(user["user_id"])
    user_row = db.get_user_by_id(user_id=user_id) or user
    display_name = str(user_row.get("display_name") or user_row.get("username") or f"user_{user_id}").strip()
    if not display_name:
        display_name = f"user_{user_id}"

    target_dir = settings.register_image_dir / "users" / f"user_{user_id}"
    stored_path = await persist_upload(file, target_dir, settings)

    try:
        replace_result = db.delete_faces_by_user(user_id=user_id, remove_image=True)
        add_result = db.add_face_with_analysis(
            person_name=display_name,
            image_path=stored_path,
            user_id=user_id,
        )
        face_id = int(add_result["face_id"])
        face_count = db.count_user_faces(user_id=user_id)
        face = {
            "face_id": face_id,
            "person_name": display_name,
            "user_id": user_id,
            "image_path": str(stored_path),
            "image_url": to_media_url(str(stored_path), settings.media_root),
        }
        return {
            "ok": True,
            "face_id": face_id,
            "face_count": face_count,
            "replaced_faces": int(replace_result.get("deleted_faces") or 0),
            "face": face,
            "face_detect": add_result.get("face_detect"),
        }
    except HTTPException:
        _safe_unlink(stored_path)
        raise
    except Exception as exc:
        _safe_unlink(stored_path)
        raise HTTPException(status_code=400, detail=str(exc))


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
