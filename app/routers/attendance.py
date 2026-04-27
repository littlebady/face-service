from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app.core.settings import Settings
from app.dependencies import get_antispoof_engine, get_current_user, get_face_db, get_liveness_manager, get_settings
from app.services import checkin_service
from app.services.antispoof_service import AntiSpoofEngine
from app.services.liveness_service import LivenessChallengeManager
from app.utils.media import haversine_m, to_media_url
from app.utils.qr import build_qr_png_data_uri
from app.utils.uploads import persist_upload
from db_manager import FaceDB


router = APIRouter(prefix="/attendance", tags=["签到场次"])


def _now_ms() -> int:
    return int(time.time() * 1000)


def _session_live_status(session: Dict[str, Any]) -> str:
    status = str(session.get("status") or "unknown")
    if status == "closed":
        return "closed"
    now_ms = _now_ms()
    start_ms = int(session.get("start_time_ms") or 0)
    end_ms = int(session.get("end_time_ms") or 0)
    if now_ms < start_ms:
        return "pending"
    if now_ms > end_ms:
        return "expired"
    return "active"


def _student_checkin_url(request: Request, token: str) -> str:
    public_base = str(os.getenv("FACE_SERVICE_PUBLIC_BASE_URL", "")).strip()
    if public_base:
        base_url = public_base.rstrip("/")
    else:
        base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/s/{token}"


def _student_checkin_url_by_mode(request: Request, token: str, *, strict_full_actions: bool) -> str:
    public_base = str(os.getenv("FACE_SERVICE_PUBLIC_BASE_URL", "")).strip()
    if public_base:
        base_url = public_base.rstrip("/")
    else:
        base_url = str(request.base_url).rstrip("/")
    if strict_full_actions:
        return f"{base_url}/s/full/{token}"
    return f"{base_url}/s/{token}"


def _serialize_session(session: Dict[str, Any], request: Request) -> Dict[str, Any]:
    payload = dict(session)
    live_status = _session_live_status(payload)
    payload["live_status"] = live_status
    payload["can_checkin"] = live_status == "active"
    payload["student_checkin_url"] = _student_checkin_url_by_mode(
        request,
        str(payload.get("qr_token") or ""),
        strict_full_actions=bool(payload.get("strict_liveness_full_actions")),
    )
    return payload


class CreateCourseRequest(BaseModel):
    course_name: str = Field(..., min_length=1, max_length=128)
    course_code: str = Field(..., min_length=1, max_length=64)


class CreateSessionRequest(BaseModel):
    course_id: Optional[int] = Field(None, ge=1)
    title: str = Field("课堂签到", min_length=1, max_length=128)
    duration_minutes: int = Field(10, ge=1, le=180)
    geofence_enabled: bool = False
    center_lat: Optional[float] = None
    center_lng: Optional[float] = None
    radius_m: float = Field(200.0, ge=10.0, le=5000.0)
    face_threshold: float = Field(0.6, ge=0.0, le=1.0)
    top_k: int = Field(1, ge=1, le=5)
    strict_liveness_required: bool = False
    strict_liveness_full_actions: bool = False
    checkin_once: bool = True


@router.get("/courses/mine", summary="当前用户场景列表")
async def list_my_courses(
    user: Dict[str, Any] = Depends(get_current_user),
    db: FaceDB = Depends(get_face_db),
):
    courses = db.list_courses_by_teacher(teacher_user_id=int(user["user_id"]))
    return {"ok": True, "courses": courses}


@router.post("/courses", summary="创建场景")
async def create_course(
    payload: CreateCourseRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    db: FaceDB = Depends(get_face_db),
):
    try:
        course = db.create_course(
            teacher_user_id=int(user["user_id"]),
            course_name=payload.course_name,
            course_code=payload.course_code,
        )
        return {"ok": True, "course": course}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/sessions", summary="发布签到")
async def create_session(
    payload: CreateSessionRequest,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
    db: FaceDB = Depends(get_face_db),
):
    if payload.geofence_enabled and (payload.center_lat is None or payload.center_lng is None):
        raise HTTPException(status_code=400, detail="启用地理围栏时必须提供中心坐标")

    now_ms = _now_ms()
    end_ms = now_ms + int(payload.duration_minutes) * 60 * 1000
    target_course_id = payload.course_id
    if target_course_id is None:
        default_course = db.ensure_default_course_for_user(user_id=int(user["user_id"]))
        target_course_id = int(default_course["course_id"])
    try:
        strict_required = bool(payload.strict_liveness_required or payload.strict_liveness_full_actions)
        session = db.create_attendance_session(
            course_id=target_course_id,
            teacher_user_id=int(user["user_id"]),
            title=payload.title,
            start_time_ms=now_ms,
            end_time_ms=end_ms,
            geofence_enabled=payload.geofence_enabled,
            center_lat=payload.center_lat,
            center_lng=payload.center_lng,
            radius_m=payload.radius_m if payload.geofence_enabled else None,
            face_threshold=payload.face_threshold,
            top_k=payload.top_k,
            strict_liveness_required=strict_required,
            checkin_once=payload.checkin_once,
            strict_liveness_full_actions=bool(payload.strict_liveness_full_actions),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    serialized = _serialize_session(session, request)
    qr_uri = build_qr_png_data_uri(serialized["student_checkin_url"])
    return {
        "ok": True,
        "session": serialized,
        "qr_data_uri": qr_uri,
    }


@router.get("/sessions", summary="我的签到场次")
async def list_sessions(
    request: Request,
    status: Optional[str] = None,
    limit: int = 20,
    user: Dict[str, Any] = Depends(get_current_user),
    db: FaceDB = Depends(get_face_db),
):
    sessions = db.list_attendance_sessions(
        teacher_user_id=int(user["user_id"]),
        status=status.strip() if status else None,
        limit=limit,
    )
    payload = [_serialize_session(item, request) for item in sessions]
    return {"ok": True, "sessions": payload}


@router.get("/sessions/{session_id}", summary="签到场次详情")
async def get_session_detail(
    session_id: int,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
    db: FaceDB = Depends(get_face_db),
):
    session = db.get_attendance_session_by_id(
        session_id=session_id,
        teacher_user_id=int(user["user_id"]),
    )
    if not session:
        raise HTTPException(status_code=404, detail="签到场次不存在")
    serialized = _serialize_session(session, request)
    return {"ok": True, "session": serialized, "summary": db.summarize_attendance_records(session_id=session_id)}


@router.post("/sessions/{session_id}/close", summary="结束签到")
async def close_session(
    session_id: int,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
    db: FaceDB = Depends(get_face_db),
):
    session = db.close_attendance_session(
        session_id=session_id,
        teacher_user_id=int(user["user_id"]),
    )
    if not session:
        raise HTTPException(status_code=404, detail="签到场次不存在")
    return {"ok": True, "session": _serialize_session(session, request)}


@router.get("/sessions/{session_id}/records", summary="查看场次签到记录")
async def list_session_records(
    session_id: int,
    limit: int = 500,
    user: Dict[str, Any] = Depends(get_current_user),
    db: FaceDB = Depends(get_face_db),
    settings: Settings = Depends(get_settings),
):
    session = db.get_attendance_session_by_id(
        session_id=session_id,
        teacher_user_id=int(user["user_id"]),
    )
    if not session:
        raise HTTPException(status_code=404, detail="签到场次不存在")
    records = db.list_attendance_records(session_id=session_id, limit=limit)
    for item in records:
        item["capture_image_url"] = to_media_url(item.get("capture_image_path"), settings.media_root)
    summary = db.summarize_attendance_records(session_id=session_id)
    return {"ok": True, "records": records, "summary": summary}


@router.get("/public/{token}", summary="扫码签到页信息")
async def get_public_session(
    token: str,
    request: Request,
    db: FaceDB = Depends(get_face_db),
):
    session = db.get_attendance_session_by_qr_token(token=token)
    if not session:
        raise HTTPException(status_code=404, detail="签到码无效")
    serialized = _serialize_session(session, request)
    return {"ok": True, "session": serialized}


@router.get("/public/{token}/qr", summary="获取签到二维码")
async def get_public_session_qr(
    token: str,
    request: Request,
    db: FaceDB = Depends(get_face_db),
):
    session = db.get_attendance_session_by_qr_token(token=token)
    if not session:
        raise HTTPException(status_code=404, detail="签到码无效")
    student_url = _student_checkin_url_by_mode(
        request,
        token,
        strict_full_actions=bool(session.get("strict_liveness_full_actions")),
    )
    return {
        "ok": True,
        "student_checkin_url": student_url,
        "qr_data_uri": build_qr_png_data_uri(student_url),
    }


@router.post("/public/{token}/liveness/verify", summary="扫码页严格活体验证并签发票据")
async def verify_public_liveness(
    token: str,
    proof: Optional[str] = Form(None, description="活体证明 JSON"),
    key_image: UploadFile = File(..., description="活体关键帧"),
    evidence_frames: Optional[List[UploadFile]] = File(None, description="活体证据帧序列"),
    db: FaceDB = Depends(get_face_db),
    settings: Settings = Depends(get_settings),
    liveness_manager: LivenessChallengeManager = Depends(get_liveness_manager),
    antispoof_engine: AntiSpoofEngine = Depends(get_antispoof_engine),
):
    session = db.get_attendance_session_by_qr_token(token=token)
    if not session:
        raise HTTPException(status_code=404, detail="签到码无效")
    if _session_live_status(session) != "active":
        raise HTTPException(status_code=400, detail="当前场次不可签到")
    if not bool(session.get("strict_liveness_required")):
        return {"ok": True, "mode": "skip", "reason": "当前场次未开启严格活体"}

    key_bytes = await key_image.read()
    await key_image.seek(0)
    key_hash = liveness_manager.sha256_hex(key_bytes)
    return await checkin_service.verify_liveness_evidence(
        db=db,
        settings=settings,
        liveness_manager=liveness_manager,
        antispoof_engine=antispoof_engine,
        proof=proof,
        key_image_hash=key_hash,
        key_image=key_image,
        evidence_frames=evidence_frames,
    )


@router.post("/public/{token}/checkin", summary="学生扫码签到提交")
async def submit_public_checkin(
    token: str,
    file: UploadFile = File(..., description="签到现场拍照"),
    lat: Optional[float] = Form(None, description="当前纬度"),
    lng: Optional[float] = Form(None, description="当前经度"),
    liveness_ticket: Optional[str] = Form(None, description="严格活体票据（可选）"),
    db: FaceDB = Depends(get_face_db),
    settings: Settings = Depends(get_settings),
    liveness_manager: LivenessChallengeManager = Depends(get_liveness_manager),
):
    session = db.get_attendance_session_by_qr_token(token=token)
    if not session:
        raise HTTPException(status_code=404, detail="签到码无效")

    live_status = _session_live_status(session)
    if live_status != "active":
        return {"ok": False, "status": "session_unavailable", "reason": f"当前签到不可用: {live_status}"}

    capture_path = await persist_upload(file, settings.checkin_image_dir / "sessions", settings)
    distance_m: Optional[float] = None
    face_detect: Optional[Dict[str, Any]] = None
    liveness_payload: Optional[Dict[str, Any]] = None

    try:
        if bool(session.get("geofence_enabled")):
            if lat is None or lng is None:
                reason = "当前场次要求定位，请允许浏览器定位权限"
                db.add_attendance_record(
                    session_id=int(session["session_id"]),
                    status="location_required",
                    reason=reason,
                    capture_image_path=capture_path,
                )
                return {"ok": False, "status": "location_required", "reason": reason}
            center_lat = session.get("center_lat")
            center_lng = session.get("center_lng")
            radius_m = session.get("radius_m")
            if center_lat is None or center_lng is None or radius_m is None:
                raise HTTPException(status_code=400, detail="签到场次地理围栏配置不完整")
            distance_m = haversine_m(float(lat), float(lng), float(center_lat), float(center_lng))
            if distance_m > float(radius_m):
                reason = f"不在签到范围内，距离 {int(distance_m)}m > {int(float(radius_m))}m"
                db.add_attendance_record(
                    session_id=int(session["session_id"]),
                    status="out_of_range",
                    reason=reason,
                    capture_image_path=capture_path,
                    lat=lat,
                    lng=lng,
                    distance_m=distance_m,
                )
                return {
                    "ok": False,
                    "status": "out_of_range",
                    "reason": reason,
                    "distance_m": distance_m,
                }

        analyzed_capture = db.analyze_face_image(capture_path)
        query_embedding = np.asarray(analyzed_capture["embedding"], dtype=np.float32)
        face_detect = dict(analyzed_capture["face_detect"])

        # Public scan flow follows per-session strict-liveness policy.
        # This keeps generic sign-in sessions usable without forcing global strict mode.
        strict_required = bool(session.get("strict_liveness_required"))
        if strict_required:
            if not (liveness_ticket and liveness_ticket.strip()):
                reason = "当前场次需要先完成严格活体校验"
                db.add_attendance_record(
                    session_id=int(session["session_id"]),
                    status="liveness_required",
                    reason=reason,
                    capture_image_path=capture_path,
                    lat=lat,
                    lng=lng,
                    distance_m=distance_m,
                )
                return {"ok": False, "status": "liveness_required", "reason": reason}
            capture_hash = liveness_manager.sha256_hex(Path(capture_path).read_bytes())
            liveness_payload = liveness_manager.consume_ticket(
                ticket=liveness_ticket,
                checkin_image_hash=capture_hash,
                checkin_face_embedding=query_embedding,
                min_face_similarity=settings.liveness_session_face_min_similarity,
            )
            if not liveness_payload.get("ok"):
                reason = f"活体会话校验失败: {liveness_payload.get('reason', '未知原因')}"
                db.add_attendance_record(
                    session_id=int(session["session_id"]),
                    status="liveness_failed",
                    reason=reason,
                    capture_image_path=capture_path,
                    lat=lat,
                    lng=lng,
                    distance_m=distance_m,
                )
                return {"ok": False, "status": "liveness_failed", "reason": reason}

        results = db.search_face(
            embedding=query_embedding,
            threshold=float(session["face_threshold"]),
            top_k=int(session["top_k"]),
        )
        if not results:
            reason = "未匹配到已注册人脸"
            db.add_attendance_record(
                session_id=int(session["session_id"]),
                status="face_not_matched",
                reason=reason,
                capture_image_path=capture_path,
                lat=lat,
                lng=lng,
                distance_m=distance_m,
            )
            return {"ok": False, "status": "face_not_matched", "reason": reason, "face_detect": face_detect}

        best = results[0]
        matched_user_id = best.get("user_id")
        if matched_user_id is None:
            reason = "该人脸尚未绑定用户，请先在个人主页注册人脸后再签到"
            db.add_attendance_record(
                session_id=int(session["session_id"]),
                status="profile_face_required",
                reason=reason,
                person_name=best.get("person_name"),
                matched_face_id=best.get("face_id"),
                similarity=best.get("similarity"),
                capture_image_path=capture_path,
                lat=lat,
                lng=lng,
                distance_m=distance_m,
            )
            return {"ok": False, "status": "profile_face_required", "reason": reason}

        matched_user = db.get_user_by_id(user_id=int(matched_user_id))
        if not matched_user or not bool(matched_user.get("is_active")):
            reason = "匹配到的人脸对应用户不可用，请联系管理员"
            db.add_attendance_record(
                session_id=int(session["session_id"]),
                status="user_unavailable",
                reason=reason,
                person_name=best.get("person_name"),
                matched_face_id=best.get("face_id"),
                matched_user_id=int(matched_user_id),
                similarity=best.get("similarity"),
                capture_image_path=capture_path,
                lat=lat,
                lng=lng,
                distance_m=distance_m,
            )
            return {"ok": False, "status": "user_unavailable", "reason": reason}

        person_name = str(matched_user.get("display_name") or matched_user.get("username") or best["person_name"])
        if bool(session.get("checkin_once")) and db.has_attendance_success_record(
            session_id=int(session["session_id"]),
            matched_user_id=int(matched_user_id),
        ):
            reason = "你已完成本场签到，无需重复提交"
            db.add_attendance_record(
                session_id=int(session["session_id"]),
                status="duplicate",
                reason=reason,
                person_name=person_name,
                matched_face_id=best.get("face_id"),
                matched_user_id=int(matched_user_id),
                similarity=best.get("similarity"),
                capture_image_path=capture_path,
                lat=lat,
                lng=lng,
                distance_m=distance_m,
            )
            return {
                "ok": False,
                "status": "duplicate",
                "reason": reason,
                "person_name": person_name,
            }

        record_id = db.add_attendance_record(
            session_id=int(session["session_id"]),
            status="success",
            reason="签到成功",
            person_name=person_name,
            matched_face_id=best.get("face_id"),
            matched_user_id=int(matched_user_id),
            similarity=best.get("similarity"),
            capture_image_path=capture_path,
            lat=lat,
            lng=lng,
            distance_m=distance_m,
        )
        db.add_checkin_record(
            capture_image_path=capture_path,
            status="success",
            reason="签到成功",
            person_name=person_name,
            matched_face_id=best.get("face_id"),
            similarity=best.get("similarity"),
            matched_image_path=best.get("image_path"),
            lat=lat,
            lng=lng,
            center_lat=session.get("center_lat"),
            center_lng=session.get("center_lng"),
            radius_m=session.get("radius_m"),
            distance_m=distance_m,
        )

        return {
            "ok": True,
            "status": "success",
            "record_id": record_id,
            "person_name": person_name,
            "matched_user_id": int(matched_user_id),
            "similarity": best.get("similarity"),
            "matched_face_id": best.get("face_id"),
            "capture_image_url": to_media_url(str(capture_path), settings.media_root),
            "distance_m": distance_m,
            "face_detect": face_detect,
            "liveness": liveness_payload,
        }
    except HTTPException:
        raise
    except Exception as exc:
        db.add_attendance_record(
            session_id=int(session["session_id"]),
            status="error",
            reason=str(exc),
            capture_image_path=capture_path,
            lat=lat,
            lng=lng,
            distance_m=distance_m,
        )
        raise HTTPException(status_code=400, detail=str(exc))
