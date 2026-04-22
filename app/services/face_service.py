from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from fastapi import HTTPException, UploadFile

from app.core.settings import Settings
from app.utils.media import serialize_face
from app.utils.uploads import persist_upload, save_upload_temp
from db_manager import FaceDB


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


async def register_face(
    *,
    db: FaceDB,
    settings: Settings,
    name: str,
    file: UploadFile,
) -> Dict[str, Any]:
    person_name = name.strip()
    if not person_name:
        raise HTTPException(status_code=400, detail="姓名不能为空")

    stored_path = await persist_upload(file, settings.register_image_dir, settings)
    try:
        add_result = db.add_face_with_analysis(person_name=person_name, image_path=stored_path)
        face_id = int(add_result["face_id"])
        face = serialize_face(
            {
                "face_id": face_id,
                "person_name": person_name,
                "image_path": str(stored_path),
            },
            settings.media_root,
        )
        return {
            "ok": True,
            "face_id": face_id,
            "face": face,
            "face_detect": add_result.get("face_detect"),
        }
    except HTTPException:
        _safe_unlink(stored_path)
        raise
    except Exception as exc:
        _safe_unlink(stored_path)
        raise HTTPException(status_code=400, detail=str(exc))


async def search_faces(
    *,
    db: FaceDB,
    settings: Settings,
    file: UploadFile,
    threshold: float,
    top_k: int,
) -> Dict[str, Any]:
    if not 0 <= threshold <= 1:
        raise HTTPException(status_code=400, detail="threshold 必须位于 0 到 1 之间")
    if top_k <= 0:
        raise HTTPException(status_code=400, detail="top_k 必须大于 0")

    temp_path = await save_upload_temp(file, settings)
    try:
        search_result = db.search_face_with_analysis(
            image_path=temp_path,
            threshold=threshold,
            top_k=top_k,
        )
        results = search_result["results"]
        return {
            "ok": True,
            "results": [serialize_face(item, settings.media_root) for item in results],
            "face_detect": search_result.get("face_detect"),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        _safe_unlink(temp_path)


def list_faces(*, db: FaceDB, settings: Settings, limit: int) -> Dict[str, Any]:
    faces = db.get_all_faces(limit=limit)
    return {"ok": True, "faces": [serialize_face(item, settings.media_root) for item in faces]}


def delete_face(*, db: FaceDB, face_id: int) -> Dict[str, Any]:
    try:
        deleted = db.delete_face(face_id=face_id, remove_image=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "deleted": deleted}
