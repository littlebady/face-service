from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os
from typing import Optional, Set


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, default: int, min_value: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(min_value, parsed)


def _env_float(name: str, default: float, min_value: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return max(min_value, parsed)


def _resolve_path(value: str, *, base_dir: Path) -> Path:
    raw = Path(value)
    if raw.is_absolute():
        return raw.resolve()
    return (base_dir / raw).resolve()


def _parse_csv(value: str, default: str) -> list[str]:
    text = value.strip() if value else default
    items = [item.strip() for item in text.split(",")]
    values = [item for item in items if item]
    return values or [default]


def _parse_extensions(value: str) -> Set[str]:
    values = [item.strip().lower() for item in value.split(",") if item.strip()]
    normalized = {item if item.startswith(".") else f".{item}" for item in values}
    return normalized or {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    data_dir: Path
    db_path: Path
    media_root: Path
    register_image_dir: Path
    checkin_image_dir: Path
    cors_origins: list[str]
    cors_allow_credentials: bool
    upload_max_bytes: int
    upload_allowed_extensions: Set[str]
    admin_token: str
    auto_geofence_min_samples: int
    auto_geofence_max_points: int
    auto_geofence_cluster_distance_m: float
    vector_backend: str
    vector_annoy_trees: int
    vector_candidate_multiplier: int
    enable_embedding_cache: bool
    query_embedding_cache_size: int
    strict_liveness_required: bool
    liveness_challenge_ttl_seconds: int
    liveness_max_proof_age_seconds: int
    liveness_min_duration_ms: int
    liveness_max_duration_ms: int
    liveness_min_motion_score: float
    liveness_max_missing_frames: int
    antispoof_model_path: Path
    antispoof_required: bool
    antispoof_min_live_score: float
    antispoof_relaxed_pass_enabled: bool
    antispoof_relaxed_min_live_score: float
    antispoof_input_size: int
    antispoof_live_class_index: int
    antispoof_preprocess_mode: str
    liveness_ticket_ttl_seconds: int
    liveness_signing_key: str
    liveness_session_face_min_similarity: float
    liveness_evidence_min_frames: int
    liveness_evidence_max_frames: int


def load_settings(base_dir: Optional[Path] = None) -> Settings:
    resolved_base = (base_dir or Path(__file__).resolve().parents[2]).resolve()
    data_dir = _resolve_path(
        os.getenv("FACE_SERVICE_DATA_DIR", str(resolved_base / "data")),
        base_dir=resolved_base,
    )
    db_path = _resolve_path(
        os.getenv("FACE_SERVICE_DB_PATH", str(data_dir / "face_database.db")),
        base_dir=resolved_base,
    )
    media_root = _resolve_path(
        os.getenv("FACE_SERVICE_MEDIA_ROOT", str(data_dir / "media")),
        base_dir=resolved_base,
    )
    upload_extensions = _parse_extensions(
        os.getenv("FACE_SERVICE_UPLOAD_ALLOWED_EXTENSIONS", ".jpg,.jpeg,.png,.bmp,.webp")
    )
    antispoof_model_path = _resolve_path(
        os.getenv("FACE_SERVICE_ANTISPOOF_MODEL_PATH", str(resolved_base / "models" / "anti_spoof" / "anti_spoof.onnx")),
        base_dir=resolved_base,
    )
    antispoof_input_size = _env_int("FACE_SERVICE_ANTISPOOF_INPUT_SIZE", 128, 32)
    antispoof_live_class_index = _env_int("FACE_SERVICE_ANTISPOOF_LIVE_CLASS_INDEX", 0, 0)
    antispoof_preprocess_mode = (os.getenv("FACE_SERVICE_ANTISPOOF_PREPROCESS_MODE", "minifas") or "").strip().lower()
    if antispoof_preprocess_mode not in {"legacy", "rgb_01", "minifas"}:
        antispoof_preprocess_mode = "minifas"
    liveness_signing_key = os.getenv("FACE_SERVICE_LIVENESS_SIGNING_KEY", "").strip()
    if not liveness_signing_key:
        # 回退到 admin token，避免空签名键导致可伪造。
        liveness_signing_key = os.getenv("FACE_SERVICE_ADMIN_TOKEN", "dev-admin-token").strip() or "dev-admin-token"
    min_liveness_duration_ms = _env_int("FACE_SERVICE_LIVENESS_MIN_DURATION_MS", 4200, 500)
    max_liveness_duration_ms = _env_int("FACE_SERVICE_LIVENESS_MAX_DURATION_MS", 25000, 1000)
    if max_liveness_duration_ms < min_liveness_duration_ms:
        max_liveness_duration_ms = min_liveness_duration_ms + 1000

    return Settings(
        base_dir=resolved_base,
        data_dir=data_dir,
        db_path=db_path,
        media_root=media_root,
        register_image_dir=media_root / "registered_faces",
        checkin_image_dir=media_root / "checkins",
        cors_origins=_parse_csv(os.getenv("FACE_SERVICE_CORS_ORIGINS", "*"), "*"),
        cors_allow_credentials=_env_bool("FACE_SERVICE_CORS_ALLOW_CREDENTIALS", False),
        upload_max_bytes=_env_int("FACE_SERVICE_UPLOAD_MAX_BYTES", 5 * 1024 * 1024, 128 * 1024),
        upload_allowed_extensions=upload_extensions,
        admin_token=os.getenv("FACE_SERVICE_ADMIN_TOKEN", "dev-admin-token").strip(),
        auto_geofence_min_samples=_env_int("FACE_SERVICE_AUTO_GEOFENCE_MIN_SAMPLES", 3, 2),
        auto_geofence_max_points=_env_int("FACE_SERVICE_AUTO_GEOFENCE_MAX_POINTS", 500, 10),
        auto_geofence_cluster_distance_m=_env_float(
            "FACE_SERVICE_AUTO_GEOFENCE_CLUSTER_DISTANCE_M",
            120.0,
            30.0,
        ),
        vector_backend=os.getenv("FACE_SERVICE_VECTOR_BACKEND", "auto").strip().lower() or "auto",
        vector_annoy_trees=_env_int("FACE_SERVICE_VECTOR_ANNOY_TREES", 20, 2),
        vector_candidate_multiplier=_env_int("FACE_SERVICE_VECTOR_CANDIDATE_MULTIPLIER", 8, 1),
        enable_embedding_cache=_env_bool("FACE_SERVICE_ENABLE_EMBEDDING_CACHE", True),
        query_embedding_cache_size=_env_int("FACE_SERVICE_QUERY_EMBEDDING_CACHE_SIZE", 256, 0),
        strict_liveness_required=_env_bool("FACE_SERVICE_STRICT_LIVENESS_REQUIRED", True),
        liveness_challenge_ttl_seconds=_env_int("FACE_SERVICE_LIVENESS_CHALLENGE_TTL_SECONDS", 45, 5),
        liveness_max_proof_age_seconds=_env_int("FACE_SERVICE_LIVENESS_MAX_PROOF_AGE_SECONDS", 180, 3),
        liveness_min_duration_ms=min_liveness_duration_ms,
        liveness_max_duration_ms=max_liveness_duration_ms,
        liveness_min_motion_score=_env_float("FACE_SERVICE_LIVENESS_MIN_MOTION_SCORE", 0.0018, 0.0),
        liveness_max_missing_frames=_env_int("FACE_SERVICE_LIVENESS_MAX_MISSING_FRAMES", 16, 0),
        antispoof_model_path=antispoof_model_path,
        antispoof_required=_env_bool("FACE_SERVICE_ANTISPOOF_REQUIRED", True),
        antispoof_min_live_score=_env_float("FACE_SERVICE_ANTISPOOF_MIN_LIVE_SCORE", 0.60, 0.0),
        antispoof_relaxed_pass_enabled=_env_bool("FACE_SERVICE_ANTISPOOF_RELAXED_PASS_ENABLED", True),
        antispoof_relaxed_min_live_score=_env_float("FACE_SERVICE_ANTISPOOF_RELAXED_MIN_LIVE_SCORE", 0.12, 0.0),
        antispoof_input_size=antispoof_input_size,
        antispoof_live_class_index=antispoof_live_class_index,
        antispoof_preprocess_mode=antispoof_preprocess_mode,
        liveness_ticket_ttl_seconds=_env_int("FACE_SERVICE_LIVENESS_TICKET_TTL_SECONDS", 180, 10),
        liveness_signing_key=liveness_signing_key,
        liveness_session_face_min_similarity=_env_float(
            "FACE_SERVICE_LIVENESS_SESSION_FACE_MIN_SIMILARITY",
            0.62,
            0.0,
        ),
        liveness_evidence_min_frames=_env_int("FACE_SERVICE_LIVENESS_EVIDENCE_MIN_FRAMES", 4, 1),
        liveness_evidence_max_frames=_env_int("FACE_SERVICE_LIVENESS_EVIDENCE_MAX_FRAMES", 16, 2),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()


def ensure_directories(settings: Optional[Settings] = None) -> None:
    cfg = settings or get_settings()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.media_root.mkdir(parents=True, exist_ok=True)
    cfg.register_image_dir.mkdir(parents=True, exist_ok=True)
    cfg.checkin_image_dir.mkdir(parents=True, exist_ok=True)
    cfg.antispoof_model_path.parent.mkdir(parents=True, exist_ok=True)
