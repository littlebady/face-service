from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from db_manager import FaceDB

from .core.logging import RequestContextMiddleware, setup_logging
from .core.settings import Settings, ensure_directories, get_settings
from .routers import admin, checkins, excel, faces, pages
from .services.antispoof_service import AntiSpoofEngine
from .services.liveness_service import LivenessChallengeManager


def create_app(settings: Settings | None = None, face_db: FaceDB | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    ensure_directories(app_settings)
    setup_logging()

    app = FastAPI(
        title="人脸签到服务 API 文档",
        description="用于人脸注册、检索、签到与管理的接口文档。",
        version="3.0.0",
        openapi_tags=[
            {"name": "页面", "description": "首页与在线测试页面"},
            {"name": "人脸管理", "description": "人脸注册、检索与列表查询"},
            {"name": "签到管理", "description": "签到记录、围栏推荐与签到校验"},
            {"name": "数据分析", "description": "签到数据分析与 Excel 导出"},
            {"name": "管理员", "description": "管理员接口（需 Bearer Token）"},
        ],
    )
    app.state.settings = app_settings
    app.state.face_db = face_db or FaceDB(
        db_path=app_settings.db_path,
        vector_backend=app_settings.vector_backend,
        enable_embedding_cache=app_settings.enable_embedding_cache,
        query_embedding_cache_size=app_settings.query_embedding_cache_size,
        vector_candidate_multiplier=app_settings.vector_candidate_multiplier,
        vector_annoy_trees=app_settings.vector_annoy_trees,
    )
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

    app.include_router(pages.router)
    app.include_router(faces.router)
    app.include_router(checkins.router)
    app.include_router(excel.router)
    app.include_router(admin.router)
    return app
