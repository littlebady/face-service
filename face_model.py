from __future__ import annotations

from pathlib import Path
import os
import sys
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

import cv2
import numpy as np

try:
    import onnxruntime as ort
except Exception:
    ort = None  # type: ignore

if TYPE_CHECKING:
    from insightface.app import FaceAnalysis

# 避免部分 Windows 环境下 OpenMP 重复加载直接崩溃
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")


_APP: Optional["FaceAnalysis"] = None

# 模型目录固定在项目内，便于部署和拷贝
BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "models"
MODEL_DIR.mkdir(exist_ok=True)


def _read_image_from_path(path: Union[str, Path]) -> Optional[np.ndarray]:
    file_path = Path(path)
    try:
        raw = np.fromfile(str(file_path), dtype=np.uint8)
    except Exception:
        return None
    if raw.size == 0:
        return None
    return cv2.imdecode(raw, cv2.IMREAD_COLOR)


def _auto_providers() -> List[str]:
    """按优先级自动选择执行 provider。"""
    if ort is None:
        return ["CPUExecutionProvider"]

    _ensure_windows_gpu_runtime_path()
    available = set(ort.get_available_providers())
    priority = [
        "CUDAExecutionProvider",
        "DmlExecutionProvider",
        "CPUExecutionProvider",
    ]
    if os.environ.get("FACE_ENABLE_TENSORRT", "0") == "1":
        priority.insert(1, "TensorrtExecutionProvider")
    picked = [item for item in priority if item in available]
    return picked or ["CPUExecutionProvider"]


def _ensure_windows_gpu_runtime_path() -> None:
    """在 Windows 下补充 torch 的 CUDA 运行时 DLL 目录到 PATH。"""
    if sys.platform != "win32":
        return

    try:
        import torch
    except Exception:
        return

    torch_dir = Path(getattr(torch, "__file__", "")).resolve().parent
    torch_lib = torch_dir / "lib"
    if not torch_lib.exists():
        return

    lib_path = str(torch_lib)
    current_path = os.environ.get("PATH", "")
    if lib_path in current_path:
        return
    os.environ["PATH"] = lib_path + os.pathsep + current_path


def get_face_app(
    name: str = "buffalo_l",
    providers: Optional[List[str]] = None,
    det_size: tuple = (640, 640),
    ctx_id: int = 0,
) -> "FaceAnalysis":
    """获取 FaceAnalysis 单例，避免重复初始化。"""
    global _APP
    if _APP is not None:
        return _APP

    # 延迟导入，避免在仅跑单测时触发重量级依赖初始化
    from insightface.app import FaceAnalysis

    selected_providers = providers or _auto_providers()
    app = FaceAnalysis(name=name, providers=selected_providers, root=str(MODEL_DIR))
    app.prepare(ctx_id=ctx_id, det_size=det_size)
    _APP = app
    return _APP


def detect_and_extract(
    img_or_path: Union[str, np.ndarray, Path],
    visualize: bool = False,
    as_list: bool = False,
) -> List[Dict[str, Any]]:
    """检测并提取人脸框、关键点和特征向量。"""
    app = get_face_app()

    if isinstance(img_or_path, Path):
        img = _read_image_from_path(img_or_path)
    elif isinstance(img_or_path, str):
        img = _read_image_from_path(img_or_path)
    else:
        img = img_or_path

    if img is None:
        raise FileNotFoundError(f"无法读取图像: {img_or_path}")

    faces = app.get(img)
    results: List[Dict[str, Any]] = []

    for face in faces:
        embedding_np = face.embedding.astype(np.float32)
        item: Dict[str, Any] = {
            "bbox": face.bbox.astype(int).tolist(),
            "kps": face.kps.astype(float).tolist(),
            "embedding": embedding_np.tolist() if as_list else embedding_np,
        }
        results.append(item)

        if visualize:
            x1, y1, x2, y2 = item["bbox"]
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
            for point in face.kps.astype(int):
                cv2.circle(img, tuple(point), 2, (0, 0, 255), -1)

    if visualize and isinstance(img_or_path, str):
        cv2.imwrite("result.jpg", img)

    return results


if __name__ == "__main__":
    try:
        result = detect_and_extract("test.jpg", visualize=False, as_list=True)
        print(f"检测到人脸数量: {len(result)}")
    except Exception as exc:
        print(f"自测失败: {exc}")
