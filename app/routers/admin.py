from __future__ import annotations

import io
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.dependencies import get_face_db, get_settings, require_admin_token
from app.services import face_service
from app.utils.media import build_checkins_csv, serialize_checkin
from db_manager import FaceDB


router = APIRouter(prefix="/admin", tags=["管理员"], dependencies=[Depends(require_admin_token)])


class BatchEmbeddingItem(BaseModel):
    person_name: str = Field(..., description="人员姓名")
    embedding: List[float] = Field(..., description="人脸特征向量")
    image_path: Optional[str] = Field(None, description="关联图片路径（可选）")


class BatchEmbeddingRequest(BaseModel):
    records: List[BatchEmbeddingItem] = Field(..., min_length=1, description="批量写入记录")


@router.get(
    "/checkins/person/{person_name}",
    summary="按姓名查询签到记录",
    description="查询指定人员的签到历史（管理员接口，需 Bearer Token）。",
)
async def list_checkins_by_person(
    person_name: str,
    limit: int = Query(100, ge=1, le=2000, description="返回记录数上限"),
    db: FaceDB = Depends(get_face_db),
    settings=Depends(get_settings),
):
    records = db.get_checkins_by_person(person_name=person_name, limit=limit)
    return {
        "ok": True,
        "person_name": person_name,
        "records": [serialize_checkin(item, settings.media_root) for item in records],
    }


@router.get(
    "/checkins/export",
    summary="导出签到记录",
    description="按条件导出 CSV 格式签到记录（管理员接口，需 Bearer Token）。",
)
async def export_checkins(
    person_name: Optional[str] = Query(None, description="按姓名筛选（可选）"),
    status: Optional[str] = Query(None, description="按状态筛选（可选）"),
    limit: int = Query(5000, ge=1, le=50000, description="导出记录数上限"),
    db: FaceDB = Depends(get_face_db),
):
    records = db.get_checkins_for_export(
        person_name=person_name.strip() if person_name else None,
        status=status.strip() if status else None,
        limit=limit,
    )
    csv_text = build_checkins_csv(records)
    stream = io.BytesIO(csv_text.encode("utf-8-sig"))
    headers = {"Content-Disposition": 'attachment; filename="checkins_export.csv"'}
    return StreamingResponse(stream, media_type="text/csv; charset=utf-8", headers=headers)


@router.delete(
    "/faces/{face_id}",
    summary="删除人脸记录",
    description="按 face_id 删除人脸记录及其关联图片（管理员接口，需 Bearer Token）。",
)
async def delete_face(
    face_id: int,
    db: FaceDB = Depends(get_face_db),
):
    return face_service.delete_face(db=db, face_id=face_id)


@router.get(
    "/vector-index/stats",
    summary="查询向量索引状态",
    description="返回当前向量索引后端、缓存状态、索引规模等信息。",
)
async def vector_index_stats(db: FaceDB = Depends(get_face_db)):
    return {"ok": True, "stats": db.get_vector_index_stats()}


@router.post(
    "/faces/batch-embeddings",
    summary="批量写入人脸特征",
    description="批量写入 embedding 数据并更新向量索引（管理员接口，需 Bearer Token）。",
)
async def batch_add_faces_by_embeddings(
    payload: BatchEmbeddingRequest,
    db: FaceDB = Depends(get_face_db),
):
    records = [
        {
            "person_name": item.person_name,
            "embedding": item.embedding,
            "image_path": item.image_path,
        }
        for item in payload.records
    ]
    result = db.add_face_embeddings_batch(records)
    return {"ok": True, "result": result, "stats": db.get_vector_index_stats()}
