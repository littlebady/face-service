from __future__ import annotations

from pathlib import Path

from app.factory import create_app
from app.core.settings import Settings, ensure_directories


app = create_app()


def create_test_app(
    *,
    db_path: Path,
    media_root: Path,
    admin_token: str = "test-admin-token",
    face_db=None,
    strict_liveness_required: bool = False,
    antispoof_required: bool = False,
    antispoof_live_class_index: int = 0,
    antispoof_preprocess_mode: str = "minifas",
):
    resolved_media = media_root.resolve()
    settings = Settings(
        base_dir=Path(__file__).resolve().parent,
        data_dir=resolved_media.parent,
        db_path=db_path.resolve(),
        media_root=resolved_media,
        register_image_dir=resolved_media / "registered_faces",
        checkin_image_dir=resolved_media / "checkins",
        cors_origins=["*"],
        cors_allow_credentials=False,
        upload_max_bytes=5 * 1024 * 1024,
        upload_allowed_extensions={".jpg", ".jpeg", ".png", ".bmp", ".webp"},
        admin_token=admin_token,
        auto_geofence_min_samples=3,
        auto_geofence_max_points=500,
        auto_geofence_cluster_distance_m=120.0,
        vector_backend="bruteforce",
        vector_annoy_trees=20,
        vector_candidate_multiplier=8,
        enable_embedding_cache=True,
        query_embedding_cache_size=128,
        strict_liveness_required=strict_liveness_required,
        liveness_challenge_ttl_seconds=45,
        liveness_max_proof_age_seconds=180,
        liveness_min_duration_ms=4200,
        liveness_max_duration_ms=25000,
        liveness_min_motion_score=0.0018,
        liveness_max_missing_frames=16,
        antispoof_model_path=(Path(__file__).resolve().parent / "models" / "anti_spoof" / "anti_spoof.onnx"),
        antispoof_required=antispoof_required,
        antispoof_min_live_score=0.60,
        antispoof_relaxed_pass_enabled=True,
        antispoof_relaxed_min_live_score=0.12,
        antispoof_input_size=128,
        antispoof_live_class_index=max(0, int(antispoof_live_class_index)),
        antispoof_preprocess_mode=(antispoof_preprocess_mode or "minifas").strip().lower() or "minifas",
        liveness_ticket_ttl_seconds=180,
        liveness_signing_key="test-liveness-signing-key",
        liveness_session_face_min_similarity=0.62,
        liveness_evidence_min_frames=2,
        liveness_evidence_max_frames=6,
    )
    ensure_directories(settings)
    return create_app(settings=settings, face_db=face_db)
