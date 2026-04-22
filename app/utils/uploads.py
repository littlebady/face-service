from __future__ import annotations

from pathlib import Path
import uuid

from fastapi import HTTPException, UploadFile

from app.core.settings import Settings


def _normalize_suffix(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix or ".jpg"


def _validate_upload_meta(file: UploadFile, settings: Settings) -> str:
    suffix = _normalize_suffix(file.filename or "")
    if suffix not in settings.upload_allowed_extensions:
        allowed = ", ".join(sorted(settings.upload_allowed_extensions))
        raise HTTPException(status_code=400, detail=f"不支持的文件类型，仅允许: {allowed}")
    if file.content_type and not file.content_type.lower().startswith("image/"):
        raise HTTPException(status_code=400, detail="上传文件必须是图片")
    return suffix


async def _read_upload_bytes(file: UploadFile, settings: Settings) -> bytes:
    content = await file.read(settings.upload_max_bytes + 1)
    if len(content) > settings.upload_max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"图片过大，最大允许 {settings.upload_max_bytes} bytes",
        )
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")
    return content


async def persist_upload(file: UploadFile, directory: Path, settings: Settings) -> Path:
    suffix = _validate_upload_meta(file, settings)
    content = await _read_upload_bytes(file, settings)

    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{suffix}"
    target_path = (directory / filename).resolve()
    target_path.write_bytes(content)
    await file.close()
    return target_path


async def save_upload_temp(file: UploadFile, settings: Settings) -> Path:
    suffix = _validate_upload_meta(file, settings)
    content = await _read_upload_bytes(file, settings)

    temp_dir = settings.data_dir / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = (temp_dir / f"{uuid.uuid4().hex}{suffix}").resolve()
    temp_path.write_bytes(content)
    await file.close()
    return temp_path
