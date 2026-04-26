from __future__ import annotations

from typing import Any, Dict

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from db_manager import FaceDB
from app.services.antispoof_service import AntiSpoofEngine
from app.services.liveness_service import LivenessChallengeManager

from .core.settings import Settings


_bearer = HTTPBearer(auto_error=False)


def _get_bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None:
        return ""
    if credentials.scheme.lower() != "bearer":
        return ""
    return str(credentials.credentials or "").strip()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_face_db(request: Request) -> FaceDB:
    return request.app.state.face_db


def get_liveness_manager(request: Request) -> LivenessChallengeManager:
    return request.app.state.liveness_manager


def get_antispoof_engine(request: Request) -> AntiSpoofEngine:
    return request.app.state.antispoof_engine


def require_admin_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.admin_token.strip()
    if not expected:
        return

    token = _get_bearer_token(credentials)
    if token != expected:
        raise HTTPException(status_code=401, detail="管理员鉴权失败")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: FaceDB = Depends(get_face_db),
) -> Dict[str, Any]:
    token = _get_bearer_token(credentials)
    if not token:
        raise HTTPException(status_code=401, detail="缺少登录凭证")

    user = db.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return user


def get_current_teacher(
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    role = str(user.get("role") or "").lower()
    if role not in {"teacher", "admin"}:
        raise HTTPException(status_code=403, detail="当前账号无教师权限")
    return user
