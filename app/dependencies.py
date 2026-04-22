from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from db_manager import FaceDB
from app.services.antispoof_service import AntiSpoofEngine
from app.services.liveness_service import LivenessChallengeManager

from .core.settings import Settings


_bearer = HTTPBearer(auto_error=False)


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

    token = ""
    if credentials is not None and credentials.scheme.lower() == "bearer":
        token = credentials.credentials

    if token != expected:
        raise HTTPException(status_code=401, detail="管理员鉴权失败")
