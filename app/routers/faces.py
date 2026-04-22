from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.core.settings import Settings
from app.dependencies import get_face_db, get_settings
from app.services import face_service
from db_manager import FaceDB


router = APIRouter(tags=["人脸管理"])


@router.post(
    "/faces/register",
    summary="注册人脸",
    description="上传姓名与人脸图片，完成人脸特征提取并写入数据库。",
)
async def register_face(
    name: str = Form(..., description="人员姓名，例如：张三"),
    file: UploadFile = File(..., description="人脸图片文件（jpg/png/webp 等）"),
    db: FaceDB = Depends(get_face_db),
    settings: Settings = Depends(get_settings),
):
    return await face_service.register_face(db=db, settings=settings, name=name, file=file)


@router.post(
    "/faces/search",
    summary="检索人脸",
    description="上传待识别人脸图片，从库中返回相似度最高的候选结果。",
)
async def search_face(
    file: UploadFile = File(..., description="待识别的人脸图片"),
    threshold: float = Form(0.6, description="相似度阈值，范围 0~1"),
    top_k: int = Form(5, description="最多返回候选数量"),
    db: FaceDB = Depends(get_face_db),
    settings: Settings = Depends(get_settings),
):
    return await face_service.search_faces(
        db=db,
        settings=settings,
        file=file,
        threshold=threshold,
        top_k=top_k,
    )


@router.get(
    "/faces",
    summary="查询人脸列表",
    description="按创建时间倒序查询已注册的人脸记录。",
)
async def list_faces(
    limit: int = Query(12, ge=1, le=100, description="返回记录数上限（1~100）"),
    db: FaceDB = Depends(get_face_db),
    settings: Settings = Depends(get_settings),
):
    return face_service.list_faces(db=db, settings=settings, limit=limit)
