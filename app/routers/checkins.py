from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.core.settings import Settings
from app.dependencies import (
    get_antispoof_engine,
    get_face_db,
    get_liveness_manager,
    get_settings,
)
from app.services import checkin_service
from app.services.antispoof_service import AntiSpoofEngine
from app.services.liveness_service import LivenessChallengeManager
from db_manager import FaceDB


router = APIRouter(tags=["签到管理"])


@router.get(
    "/checkins",
    summary="查询签到记录",
    description="查询最近的签到记录列表。",
)
async def list_checkins(
    limit: int = Query(12, ge=1, le=100, description="返回记录数量上限（1~100）"),
    db: FaceDB = Depends(get_face_db),
    settings: Settings = Depends(get_settings),
):
    return checkin_service.list_checkins(db=db, settings=settings, limit=limit)


@router.post(
    "/checkins/liveness/challenge",
    summary="获取严格活体挑战",
    description="下发一次性随机动作挑战，用于严格活体检测流程。",
)
async def create_liveness_challenge(
    liveness_manager: LivenessChallengeManager = Depends(get_liveness_manager),
):
    return liveness_manager.create_challenge()


@router.post(
    "/checkins/liveness/verify",
    summary="复核活体证据并签发会话票据",
    description="上传短证据片段（关键帧+若干证据帧），后端执行 anti-spoof 与证明校验，签发一次性 liveness_ticket。",
)
async def verify_liveness_evidence(
    proof: Optional[str] = Form(None, description="活体动作证明（JSON 字符串）"),
    key_image_hash: str = Form(..., description="关键帧图片 SHA256（hex）"),
    key_image: UploadFile = File(..., description="关键帧图片（用于会话绑定）"),
    evidence_frames: Optional[List[UploadFile]] = File(None, description="短证据帧序列（可多张）"),
    db: FaceDB = Depends(get_face_db),
    settings: Settings = Depends(get_settings),
    liveness_manager: LivenessChallengeManager = Depends(get_liveness_manager),
    antispoof_engine: AntiSpoofEngine = Depends(get_antispoof_engine),
):
    return await checkin_service.verify_liveness_evidence(
        db=db,
        settings=settings,
        liveness_manager=liveness_manager,
        antispoof_engine=antispoof_engine,
        proof=proof,
        key_image_hash=key_image_hash,
        key_image=key_image,
        evidence_frames=evidence_frames,
    )


@router.get(
    "/checkins/geofence/suggest",
    summary="推荐围栏",
    description="基于历史成功签到点聚类，自动给出围栏中心与半径。",
)
async def suggest_geofence(
    person_name: Optional[str] = Query(None, description="按姓名筛选历史签到点（可选）"),
    min_samples: int = Query(3, ge=2, le=100, description="聚类最少样本数"),
    max_points: int = Query(500, ge=10, le=5000, description="最多使用的历史点数量"),
    cluster_distance_m: float = Query(120.0, ge=30.0, le=1000.0, description="聚类距离阈值（米）"),
    db: FaceDB = Depends(get_face_db),
):
    return checkin_service.suggest_geofence(
        db=db,
        person_name=person_name,
        min_samples=min_samples,
        max_points=max_points,
        cluster_distance_m=cluster_distance_m,
    )


@router.post(
    "/checkin",
    summary="执行签到",
    description="上传现场人脸与位置信息，进行活体、人脸、围栏校验后返回签到结果。",
)
async def checkin(
    file: UploadFile = File(..., description="签到现场抓拍图"),
    lat: float = Form(..., description="当前纬度"),
    lng: float = Form(..., description="当前经度"),
    threshold: float = Form(0.6, description="人脸相似度阈值，范围 0~1"),
    top_k: int = Form(1, description="匹配候选数量，签到默认 1"),
    center_lat: Optional[float] = Form(None, description="围栏中心纬度（可选）"),
    center_lng: Optional[float] = Form(None, description="围栏中心经度（可选）"),
    radius_m: Optional[float] = Form(200.0, description="围栏半径（米）"),
    auto_geofence: bool = Form(True, description="缺省围栏时是否自动推荐"),
    geofence_person_name: Optional[str] = Form(None, description="用于推荐围栏的姓名（可选）"),
    liveness_proof: Optional[str] = Form(None, description="兼容旧版活体证明（JSON 字符串）"),
    liveness_ticket: Optional[str] = Form(None, description="严格版活体会话票据"),
    db: FaceDB = Depends(get_face_db),
    liveness_manager: LivenessChallengeManager = Depends(get_liveness_manager),
    settings: Settings = Depends(get_settings),
):
    return await checkin_service.checkin(
        db=db,
        settings=settings,
        file=file,
        lat=lat,
        lng=lng,
        threshold=threshold,
        top_k=top_k,
        center_lat=center_lat,
        center_lng=center_lng,
        radius_m=radius_m,
        auto_geofence=auto_geofence,
        geofence_person_name=geofence_person_name,
        liveness_proof=liveness_proof,
        liveness_ticket=liveness_ticket,
        liveness_manager=liveness_manager,
    )
