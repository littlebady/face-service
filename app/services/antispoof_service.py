from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

import cv2
import numpy as np

try:
    import onnxruntime as ort
except Exception:
    ort = None  # type: ignore


def _softmax(values: np.ndarray) -> np.ndarray:
    logits = np.asarray(values, dtype=np.float32).reshape(-1)
    if logits.size == 0:
        return np.asarray([0.0], dtype=np.float32)
    shifted = logits - float(np.max(logits))
    exp = np.exp(shifted)
    denom = float(np.sum(exp))
    if denom <= 0:
        return np.zeros_like(exp)
    return exp / denom


def _sigmoid(value: float) -> float:
    value = float(value)
    if value >= 0:
        z = np.exp(-value)
        return float(1.0 / (1.0 + z))
    z = np.exp(value)
    return float(z / (1.0 + z))


def _auto_providers() -> List[str]:
    if ort is None:
        return ["CPUExecutionProvider"]
    available = set(ort.get_available_providers())
    order = ["CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"]
    picked = [name for name in order if name in available]
    return picked or ["CPUExecutionProvider"]


@dataclass
class AntiSpoofScore:
    live_score: float
    raw_output: List[float]


class AntiSpoofEngine:
    """ONNX anti-spoof classifier wrapper."""

    def __init__(
        self,
        *,
        model_path: Path,
        input_size: int = 128,
        live_class_index: int = 0,
        preprocess_mode: str = "minifas",
        providers: Optional[Sequence[str]] = None,
    ):
        self.model_path = Path(model_path).resolve()
        self.input_size = max(32, int(input_size))
        self.live_class_index = max(0, int(live_class_index))
        self.preprocess_mode = self._normalize_preprocess_mode(preprocess_mode)
        self.providers = list(providers) if providers else _auto_providers()
        self._session = None
        self._input_name: Optional[str] = None
        self._input_hw: Tuple[int, int] = (self.input_size, self.input_size)
        self._is_nchw = True

    @staticmethod
    def _normalize_preprocess_mode(mode: str) -> str:
        normalized = (mode or "").strip().lower()
        if normalized in {"legacy", "rgb_01", "minifas"}:
            return normalized
        return "minifas"

    def _ensure_session(self) -> None:
        if self._session is not None:
            return
        if ort is None:
            raise RuntimeError("onnxruntime 未安装，无法执行 anti-spoof 推理")
        if not self.model_path.exists():
            raise FileNotFoundError(f"anti-spoof 模型不存在: {self.model_path}")

        session = ort.InferenceSession(str(self.model_path), providers=self.providers)
        inputs = session.get_inputs()
        if not inputs:
            raise RuntimeError("anti-spoof 模型输入为空")
        main_input = inputs[0]
        self._input_name = main_input.name
        self._is_nchw, self._input_hw = self._resolve_layout_and_size(main_input.shape)
        self._session = session

    def _resolve_layout_and_size(self, shape: Sequence[Any]) -> Tuple[bool, Tuple[int, int]]:
        if len(shape) != 4:
            return True, (self.input_size, self.input_size)

        # NCHW: [N, C, H, W]
        if shape[1] in (1, 3):
            h = int(shape[2]) if isinstance(shape[2], int) and shape[2] > 0 else self.input_size
            w = int(shape[3]) if isinstance(shape[3], int) and shape[3] > 0 else self.input_size
            return True, (h, w)

        # NHWC: [N, H, W, C]
        if shape[3] in (1, 3):
            h = int(shape[1]) if isinstance(shape[1], int) and shape[1] > 0 else self.input_size
            w = int(shape[2]) if isinstance(shape[2], int) and shape[2] > 0 else self.input_size
            return False, (h, w)

        return True, (self.input_size, self.input_size)

    @staticmethod
    def _reflect_letterbox(image_bgr: np.ndarray, target_hw: Tuple[int, int]) -> np.ndarray:
        target_h, target_w = target_hw
        src_h, src_w = image_bgr.shape[:2]
        if src_h <= 0 or src_w <= 0:
            raise ValueError("anti-spoof 输入图像为空")
        scale = min(target_w / float(src_w), target_h / float(src_h))
        resized_w = max(1, int(round(src_w * scale)))
        resized_h = max(1, int(round(src_h * scale)))
        resized = cv2.resize(image_bgr, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)

        pad_w = max(0, target_w - resized_w)
        pad_h = max(0, target_h - resized_h)
        left = pad_w // 2
        right = pad_w - left
        top = pad_h // 2
        bottom = pad_h - top
        if top == 0 and bottom == 0 and left == 0 and right == 0:
            return resized
        return cv2.copyMakeBorder(
            resized,
            top,
            bottom,
            left,
            right,
            borderType=cv2.BORDER_REFLECT_101,
        )

    def _preprocess(self, image_bgr: np.ndarray) -> np.ndarray:
        if image_bgr is None or image_bgr.size == 0:
            raise ValueError("anti-spoof 输入图像为空")
        h, w = self._input_hw
        if self.preprocess_mode == "minifas":
            prepared = self._reflect_letterbox(image_bgr, (h, w))
            rgb = cv2.cvtColor(prepared, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            normalized = rgb
        elif self.preprocess_mode == "rgb_01":
            resized = cv2.resize(image_bgr, (w, h), interpolation=cv2.INTER_LINEAR)
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            normalized = rgb
        else:
            resized = cv2.resize(image_bgr, (w, h), interpolation=cv2.INTER_LINEAR)
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            normalized = (rgb - 0.5) / 0.5
        if self._is_nchw:
            tensor = np.transpose(normalized, (2, 0, 1))[None, ...]
        else:
            tensor = normalized[None, ...]
        return np.asarray(tensor, dtype=np.float32)

    def score(self, image_bgr: np.ndarray) -> AntiSpoofScore:
        self._ensure_session()
        assert self._session is not None and self._input_name is not None
        input_tensor = self._preprocess(image_bgr)
        outputs = self._session.run(None, {self._input_name: input_tensor})
        if not outputs:
            raise RuntimeError("anti-spoof 模型未返回输出")
        raw = np.asarray(outputs[0], dtype=np.float32).reshape(-1)
        if raw.size == 1:
            live_prob = _sigmoid(float(raw[0]))
        else:
            probs = _softmax(raw)
            live_idx = min(self.live_class_index, max(0, probs.size - 1))
            live_prob = float(probs[live_idx])
        return AntiSpoofScore(
            live_score=max(0.0, min(1.0, live_prob)),
            raw_output=[float(x) for x in raw.tolist()],
        )

    def score_many(self, images_bgr: Sequence[np.ndarray]) -> List[AntiSpoofScore]:
        results: List[AntiSpoofScore] = []
        for image in images_bgr:
            results.append(self.score(image))
        return results
