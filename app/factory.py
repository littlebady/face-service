from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from db_manager import FaceDB

from .core.logging import RequestContextMiddleware, setup_logging
from .core.settings import Settings, ensure_directories, get_settings
from .routers import admin, attendance, auth, checkins, excel, faces, pages, portal
from .services.antispoof_service import AntiSpoofEngine
from .services.liveness_service import LivenessChallengeManager


def _build_face_db(app_settings: Settings, face_db: FaceDB | None) -> FaceDB:
    if face_db is not None:
        return face_db

    try:
        return FaceDB(
            db_path=app_settings.db_path,
            vector_backend=app_settings.vector_backend,
            enable_embedding_cache=app_settings.enable_embedding_cache,
            query_embedding_cache_size=app_settings.query_embedding_cache_size,
            vector_candidate_multiplier=app_settings.vector_candidate_multiplier,
            vector_annoy_trees=app_settings.vector_annoy_trees,
        )
    except Exception:
        # Development fallback: if persistent DB is unavailable, keep service usable with in-memory DB.
        return FaceDB(
            db_path=":memory:",
            vector_backend=app_settings.vector_backend,
            enable_embedding_cache=app_settings.enable_embedding_cache,
            query_embedding_cache_size=app_settings.query_embedding_cache_size,
            vector_candidate_multiplier=app_settings.vector_candidate_multiplier,
            vector_annoy_trees=app_settings.vector_annoy_trees,
        )


def create_app(settings: Settings | None = None, face_db: FaceDB | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    ensure_directories(app_settings)
    setup_logging()

    app = FastAPI(
        title="Universal Face Check-in Service API",
        description="Universal sign-in platform: register/login, publish sign-in sessions, and QR check-in.",
        version="4.1.0",
        openapi_tags=[
            {"name": "Portal", "description": "Web pages for login, dashboard and scan check-in"},
            {"name": "认证", "description": "账号注册、登录、登出"},
            {"name": "签到场次", "description": "发布签到、查看场次、扫码签到"},
            {"name": "Legacy Pages", "description": "旧版页面入口（兼容）"},
            {"name": "人脸管理", "description": "人脸注册、检索、列表"},
            {"name": "签到管理", "description": "旧版签到接口（兼容）"},
            {"name": "数据分析", "description": "签到分析和导出"},
            {"name": "管理员", "description": "管理员接口（Bearer Token）"},
        ],
    )

    app.state.settings = app_settings
    app.state.face_db = _build_face_db(app_settings, face_db)
    app.state.liveness_manager = LivenessChallengeManager(
        ttl_seconds=app_settings.liveness_challenge_ttl_seconds,
        signing_key=app_settings.liveness_signing_key,
        ticket_ttl_seconds=app_settings.liveness_ticket_ttl_seconds,
    )
    app.state.antispoof_engine = AntiSpoofEngine(
        model_path=app_settings.antispoof_model_path,
        input_size=app_settings.antispoof_input_size,
        live_class_index=app_settings.antispoof_live_class_index,
        preprocess_mode=app_settings.antispoof_preprocess_mode,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=app_settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    static_root = (app_settings.base_dir / "app" / "static").resolve()
    static_root.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_root)), name="static")
    app.mount("/media", StaticFiles(directory=str(app_settings.media_root)), name="media")

    app.include_router(portal.router)
    app.include_router(auth.router)
    app.include_router(attendance.router)
    app.include_router(pages.router)
    app.include_router(faces.router)
    app.include_router(checkins.router)
    app.include_router(excel.router)
    app.include_router(admin.router)
    return app
