from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from fastapi import HTTPException, UploadFile

from app.core.settings import Settings
from app.services.antispoof_service import AntiSpoofEngine
from app.services.liveness_service import LivenessChallengeManager
from app.utils.media import haversine_m, serialize_checkin, to_media_url
from app.utils.uploads import persist_upload
from db_manager import FaceDB


_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def list_checkins(*, db: FaceDB, settings: Settings, limit: int) -> Dict[str, Any]:
    records = db.get_recent_checkins(limit=limit)
    return {"ok": True, "records": [serialize_checkin(item, settings.media_root) for item in records]}


def suggest_geofence(
    *,
    db: FaceDB,
    person_name: Optional[str],
    min_samples: int,
    max_points: int,
    cluster_distance_m: float,
) -> Dict[str, Any]:
    return db.suggest_geofence_from_history(
        person_name=person_name.strip() if person_name else None,
        min_samples=min_samples,
        max_points=max_points,
        cluster_distance_m=cluster_distance_m,
    )


def _sanitize_sha256_hex(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256_HEX_RE.match(normalized):
        raise HTTPException(status_code=400, detail="key_image_hash 必须是 64 位 sha256 十六进制字符串")
    return normalized


async def _read_upload_image(file: UploadFile, settings: Settings, *, label: str) -> Tuple[bytes, np.ndarray]:
    try:
        if file.content_type and not file.content_type.lower().startswith("image/"):
            raise HTTPException(status_code=400, detail=f"{label} 必须是图片")
        raw = await file.read(settings.upload_max_bytes + 1)
        if len(raw) > settings.upload_max_bytes:
            raise HTTPException(status_code=413, detail=f"{label} 过大，超过 {settings.upload_max_bytes} bytes")
        if not raw:
            raise HTTPException(status_code=400, detail=f"{label} 为空")
        arr = np.frombuffer(raw, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None or image.size == 0:
            raise HTTPException(status_code=400, detail=f"{label} 无法解码")
        return raw, image
    finally:
        await file.close()


def _crop_face_region(image: np.ndarray, bbox: Optional[Sequence[float]], pad_ratio: float = 0.18) -> np.ndarray:
    if image is None or image.size == 0:
        raise ValueError("空图像")
    if not bbox or len(bbox) < 4:
        return image
    h, w = image.shape[:2]
    x1, y1, x2, y2 = [float(x) for x in bbox[:4]]
    fw = max(1.0, x2 - x1)
    fh = max(1.0, y2 - y1)
    pad_x = fw * float(pad_ratio)
    pad_y = fh * float(pad_ratio)
    left = max(0, int(round(x1 - pad_x)))
    top = max(0, int(round(y1 - pad_y)))
    right = min(w, int(round(x2 + pad_x)))
    bottom = min(h, int(round(y2 + pad_y)))
    if right <= left or bottom <= top:
        return image
    return image[top:bottom, left:right]


def _aggregate_live_score(frame_scores: Sequence[float]) -> Tuple[float, Dict[str, float]]:
    if not frame_scores:
        stats = {"mean": 0.0, "median": 0.0, "top_half_mean": 0.0}
        return 0.0, stats

    values = np.asarray(frame_scores, dtype=np.float32).reshape(-1)
    mean_score = float(np.mean(values))
    median_score = float(np.median(values))
    sorted_desc = np.sort(values)[::-1]
    top_n = max(1, int(np.ceil(sorted_desc.size * 0.5)))
    top_half_mean = float(np.mean(sorted_desc[:top_n]))

    # Pass-rate 优先：用更抗抖动的聚合，避免少数坏帧把真人分数拉低。
    effective_score = max(mean_score, median_score, top_half_mean)
    stats = {
        "mean": mean_score,
        "median": median_score,
        "top_half_mean": top_half_mean,
    }
    return effective_score, stats


async def verify_liveness_evidence(
    *,
    db: FaceDB,
    settings: Settings,
    liveness_manager: LivenessChallengeManager,
    antispoof_engine: AntiSpoofEngine,
    proof: Optional[str],
    key_image_hash: str,
    key_image: UploadFile,
    evidence_frames: Optional[List[UploadFile]],
) -> Dict[str, Any]:
    normalized_hash = _sanitize_sha256_hex(key_image_hash)
    key_bytes, key_image_np = await _read_upload_image(key_image, settings, label="key_image")

    computed_hash = liveness_manager.sha256_hex(key_bytes)
    if computed_hash != normalized_hash:
        raise HTTPException(status_code=400, detail="key_image_hash 与 key_image 内容不匹配")

    proof_result = liveness_manager.verify_proof(
        proof_raw=proof,
        max_proof_age_seconds=settings.liveness_max_proof_age_seconds,
        min_duration_ms=settings.liveness_min_duration_ms,
        max_duration_ms=settings.liveness_max_duration_ms,
        min_motion_score=settings.liveness_min_motion_score,
        max_missing_frames=settings.liveness_max_missing_frames,
        consume_challenge=True,
    )
    if not proof_result.get("ok"):
        return {"ok": False, "status": "liveness_failed", "reason": proof_result.get("reason", "活体证明校验失败")}

    key_face = db.analyze_face_array(key_image_np, source="key_image")
    key_embedding = np.asarray(key_face["embedding"], dtype=np.float32)

    min_frames = max(1, int(settings.liveness_evidence_min_frames))
    max_frames = max(min_frames, int(settings.liveness_evidence_max_frames))
    frame_images: List[np.ndarray] = [key_image_np]

    frame_files = evidence_frames or []
    for idx, frame_file in enumerate(frame_files[: max(0, max_frames - 1)]):
        _, frame_img = await _read_upload_image(frame_file, settings, label=f"evidence_frames[{idx}]")
        frame_images.append(frame_img)

    if len(frame_images) < min_frames:
        return {
            "ok": False,
            "status": "liveness_failed",
            "reason": f"证据帧不足：需要至少 {min_frames} 帧，实际 {len(frame_images)} 帧",
        }

    frame_scores: List[float] = []
    valid_face_frames = 0
    model_status = "loaded"

    try:
        for idx, frame_img in enumerate(frame_images):
            analyzed = db.analyze_face_array(frame_img, source=f"evidence_frame_{idx}")
            face_crop = _crop_face_region(frame_img, analyzed["face_detect"].get("selected_face_bbox"))
            score = antispoof_engine.score(face_crop).live_score
            frame_scores.append(float(score))
            valid_face_frames += 1
    except FileNotFoundError as exc:
        if settings.antispoof_required:
            return {
                "ok": False,
                "status": "liveness_failed",
                "reason": f"anti-spoof 模型缺失：{exc}",
            }
        model_status = "missing_optional"
    except RuntimeError as exc:
        if settings.antispoof_required:
            return {
                "ok": False,
                "status": "liveness_failed",
                "reason": f"anti-spoof 推理失败：{exc}",
            }
        model_status = "runtime_optional"

    if model_status != "loaded":
        frame_scores = [1.0 for _ in range(len(frame_images))]
        valid_face_frames = len(frame_images)

    if valid_face_frames < min_frames:
        return {
            "ok": False,
            "status": "liveness_failed",
            "reason": f"有效人脸证据帧不足：需要至少 {min_frames} 帧，实际 {valid_face_frames} 帧",
        }

    live_score, score_stats = _aggregate_live_score(frame_scores)
    strict_threshold = float(settings.antispoof_min_live_score)
    relaxed_threshold = min(strict_threshold, float(settings.antispoof_relaxed_min_live_score))
    relaxed_enabled = bool(settings.antispoof_relaxed_pass_enabled)
    decision = "strict_pass"
    if settings.antispoof_required and live_score < strict_threshold:
        if relaxed_enabled and live_score >= relaxed_threshold:
            decision = "relaxed_pass"
        else:
            return {
                "ok": False,
                "status": "liveness_failed",
                "reason": f"anti-spoof 复核失败：live_score={live_score:.3f} < strict_threshold={strict_threshold:.3f}",
                "anti_spoof": {
                    "model_status": model_status,
                    "live_score": live_score,
                    "threshold": strict_threshold,
                    "strict_threshold": strict_threshold,
                    "relaxed_threshold": relaxed_threshold,
                    "relaxed_enabled": relaxed_enabled,
                    "decision": "failed",
                    "score_stats": {k: round(v, 6) for k, v in score_stats.items()},
                    "frame_scores": [round(x, 6) for x in frame_scores],
                    "valid_face_frames": valid_face_frames,
                },
            }

    evidence_features = {
        "proof_metrics": proof_result.get("metrics", {}),
        "evidence_frames": len(frame_images),
        "valid_face_frames": valid_face_frames,
        "anti_spoof_model": str(settings.antispoof_model_path.name),
        "anti_spoof_model_status": model_status,
        "anti_spoof_decision": decision,
        "anti_spoof_score_stats": {k: round(v, 6) for k, v in score_stats.items()},
        "anti_spoof_frame_scores": [round(x, 6) for x in frame_scores[:16]],
    }
    ticket_result = liveness_manager.issue_ticket(
        challenge_id=str(proof_result.get("challenge_id")),
        key_image_hash=normalized_hash,
        key_face_embedding=key_embedding,
        anti_spoof_score=live_score,
        evidence_features=evidence_features,
    )
    if not ticket_result.get("ok"):
        return {
            "ok": False,
            "status": "liveness_failed",
            "reason": "会话票据签发失败",
        }

    return {
        "ok": True,
        "mode": "strict",
        "liveness": proof_result,
        "anti_spoof": {
            "model_status": model_status,
            "live_score": live_score,
            "threshold": strict_threshold,
            "strict_threshold": strict_threshold,
            "relaxed_threshold": relaxed_threshold,
            "relaxed_enabled": relaxed_enabled,
            "decision": decision,
            "score_stats": {k: round(v, 6) for k, v in score_stats.items()},
            "frame_scores": [round(x, 6) for x in frame_scores],
            "valid_face_frames": valid_face_frames,
        },
        "session": {
            "session_id": ticket_result["session_id"],
            "issued_at_ms": ticket_result["issued_at_ms"],
            "expires_at_ms": ticket_result["expires_at_ms"],
        },
        "liveness_ticket": ticket_result["liveness_ticket"],
    }


async def checkin(
    *,
    db: FaceDB,
    settings: Settings,
    file: UploadFile,
    lat: float,
    lng: float,
    threshold: float,
    top_k: int,
    center_lat: Optional[float],
    center_lng: Optional[float],
    radius_m: Optional[float],
    auto_geofence: bool,
    geofence_person_name: Optional[str],
    liveness_proof: Optional[str],
    liveness_ticket: Optional[str],
    liveness_manager: LivenessChallengeManager,
) -> Dict[str, Any]:
    if not 0 <= threshold <= 1:
        raise HTTPException(status_code=400, detail="threshold 必须位于 0 到 1 之间")
    if top_k <= 0:
        raise HTTPException(status_code=400, detail="top_k 必须大于 0")
    if radius_m is not None and radius_m <= 0:
        raise HTTPException(status_code=400, detail="radius_m 必须大于 0")

    capture_path = await persist_upload(file, settings.checkin_image_dir, settings)
    distance_m: Optional[float] = None
    geofence_auto_applied = False
    geofence_cluster_size: Optional[int] = None
    face_detect: Optional[Dict[str, Any]] = None
    liveness_verify: Optional[Dict[str, Any]] = None

    try:
        if auto_geofence and (center_lat is None or center_lng is None):
            suggestion = db.suggest_geofence_from_history(
                person_name=geofence_person_name.strip() if geofence_person_name else None,
                min_samples=settings.auto_geofence_min_samples,
                max_points=settings.auto_geofence_max_points,
                cluster_distance_m=settings.auto_geofence_cluster_distance_m,
            )
            if suggestion.get("ok"):
                center_lat = float(suggestion["center_lat"])
                center_lng = float(suggestion["center_lng"])
                radius_m = float(suggestion["radius_m"])
                geofence_auto_applied = True
                geofence_cluster_size = suggestion.get("cluster_size")

        if center_lat is not None or center_lng is not None:
            if center_lat is None or center_lng is None:
                raise HTTPException(status_code=400, detail="围栏中心纬度和经度需要同时提供")
            distance_m = haversine_m(lat, lng, center_lat, center_lng)
            if radius_m is not None and distance_m > radius_m:
                reason = f"不在签到范围内，距离{int(distance_m)}m > {int(radius_m)}m"
                checkin_id = db.add_checkin_record(
                    capture_image_path=capture_path,
                    status="out_of_range",
                    reason=reason,
                    lat=lat,
                    lng=lng,
                    center_lat=center_lat,
                    center_lng=center_lng,
                    radius_m=radius_m,
                    distance_m=distance_m,
                )
                return {
                    "ok": False,
                    "checkin_id": checkin_id,
                    "status": "out_of_range",
                    "reason": reason,
                    "capture_image_url": to_media_url(str(capture_path), settings.media_root),
                    "center_lat": center_lat,
                    "center_lng": center_lng,
                    "radius_m": radius_m,
                    "geofence_auto_applied": geofence_auto_applied,
                    "geofence_cluster_size": geofence_cluster_size,
                    "face_detect": face_detect,
                    "liveness": liveness_verify,
                }

        analyzed_capture = db.analyze_face_image(capture_path)
        query_embedding = np.asarray(analyzed_capture["embedding"], dtype=np.float32)
        face_detect = dict(analyzed_capture["face_detect"])

        strict_requires_ticket = settings.strict_liveness_required
        if strict_requires_ticket and not (liveness_ticket and liveness_ticket.strip()):
            reason = "严格模式必须先完成证据复核并携带 liveness_ticket"
            checkin_id = db.add_checkin_record(
                capture_image_path=capture_path,
                status="liveness_failed",
                reason=reason,
                lat=lat,
                lng=lng,
                center_lat=center_lat,
                center_lng=center_lng,
                radius_m=radius_m,
                distance_m=distance_m,
            )
            return {
                "ok": False,
                "checkin_id": checkin_id,
                "status": "liveness_failed",
                "reason": reason,
                "capture_image_url": to_media_url(str(capture_path), settings.media_root),
                "center_lat": center_lat,
                "center_lng": center_lng,
                "radius_m": radius_m,
                "geofence_auto_applied": geofence_auto_applied,
                "geofence_cluster_size": geofence_cluster_size,
                "face_detect": face_detect,
                "liveness": liveness_verify,
            }

        if liveness_ticket and liveness_ticket.strip():
            capture_bytes = Path(capture_path).read_bytes()
            capture_hash = liveness_manager.sha256_hex(capture_bytes)
            liveness_verify = liveness_manager.consume_ticket(
                ticket=liveness_ticket,
                checkin_image_hash=capture_hash,
                checkin_face_embedding=query_embedding,
                min_face_similarity=settings.liveness_session_face_min_similarity,
            )
            if not liveness_verify.get("ok"):
                reason = f"活体会话校验失败：{liveness_verify.get('reason', '未知原因')}"
                checkin_id = db.add_checkin_record(
                    capture_image_path=capture_path,
                    status="liveness_failed",
                    reason=reason,
                    lat=lat,
                    lng=lng,
                    center_lat=center_lat,
                    center_lng=center_lng,
                    radius_m=radius_m,
                    distance_m=distance_m,
                )
                return {
                    "ok": False,
                    "checkin_id": checkin_id,
                    "status": "liveness_failed",
                    "reason": reason,
                    "capture_image_url": to_media_url(str(capture_path), settings.media_root),
                    "center_lat": center_lat,
                    "center_lng": center_lng,
                    "radius_m": radius_m,
                    "geofence_auto_applied": geofence_auto_applied,
                    "geofence_cluster_size": geofence_cluster_size,
                    "face_detect": face_detect,
                    "liveness": liveness_verify,
                }
        elif liveness_proof and liveness_proof.strip():
            # 兼容旧流程（非严格模式）。
            liveness_verify = liveness_manager.verify_proof(
                proof_raw=liveness_proof,
                max_proof_age_seconds=settings.liveness_max_proof_age_seconds,
                min_duration_ms=settings.liveness_min_duration_ms,
                max_duration_ms=settings.liveness_max_duration_ms,
                min_motion_score=settings.liveness_min_motion_score,
                max_missing_frames=settings.liveness_max_missing_frames,
                consume_challenge=True,
            )

        results = db.search_face(
            embedding=query_embedding,
            threshold=threshold,
            top_k=top_k,
        )

        if not results:
            checkin_id = db.add_checkin_record(
                capture_image_path=capture_path,
                status="face_not_matched",
                reason="未通过人脸比对",
                lat=lat,
                lng=lng,
                center_lat=center_lat,
                center_lng=center_lng,
                radius_m=radius_m,
                distance_m=distance_m,
            )
            return {
                "ok": False,
                "checkin_id": checkin_id,
                "status": "face_not_matched",
                "reason": "未通过人脸比对",
                "capture_image_url": to_media_url(str(capture_path), settings.media_root),
                "center_lat": center_lat,
                "center_lng": center_lng,
                "radius_m": radius_m,
                "geofence_auto_applied": geofence_auto_applied,
                "geofence_cluster_size": geofence_cluster_size,
                "face_detect": face_detect,
                "liveness": liveness_verify,
            }

        best = results[0]
        checkin_id = db.add_checkin_record(
            capture_image_path=capture_path,
            status="success",
            reason="签到成功",
            person_name=best["person_name"],
            matched_face_id=best["face_id"],
            similarity=best["similarity"],
            matched_image_path=best["image_path"],
            lat=lat,
            lng=lng,
            center_lat=center_lat,
            center_lng=center_lng,
            radius_m=radius_m,
            distance_m=distance_m,
        )
        return {
            "ok": True,
            "checkin_id": checkin_id,
            "status": "success",
            "person_name": best["person_name"],
            "similarity": best["similarity"],
            "matched_face_id": best["face_id"],
            "matched_image_url": to_media_url(best["image_path"], settings.media_root),
            "capture_image_url": to_media_url(str(capture_path), settings.media_root),
            "distance_m": distance_m,
            "center_lat": center_lat,
            "center_lng": center_lng,
            "radius_m": radius_m,
            "geofence_auto_applied": geofence_auto_applied,
            "geofence_cluster_size": geofence_cluster_size,
            "face_detect": face_detect,
            "liveness": liveness_verify,
        }
    except HTTPException:
        raise
    except Exception as exc:
        checkin_id = db.add_checkin_record(
            capture_image_path=capture_path,
            status="error",
            reason=str(exc),
            lat=lat,
            lng=lng,
            center_lat=center_lat,
            center_lng=center_lng,
            radius_m=radius_m,
            distance_m=distance_m,
        )
        raise HTTPException(status_code=400, detail=f"{exc} (record_id={checkin_id})")
