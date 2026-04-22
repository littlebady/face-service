from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import base64
import hmac
import json
import secrets
import time
from threading import Lock
from typing import Any, Dict, List, Optional

import numpy as np


_STRICT_ACTION_POOL = ["blink", "turn_left", "turn_right", "mouth_open", "move_closer"]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padded = data + "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


@dataclass
class LivenessChallenge:
    challenge_id: str
    nonce: str
    actions: List[str]
    issued_at_ms: int
    expires_at_ms: int
    used: bool = False


@dataclass
class VerifiedLivenessSession:
    session_id: str
    challenge_id: str
    key_image_hash: str
    key_face_embedding: np.ndarray
    anti_spoof_score: float
    issued_at_ms: int
    expires_at_ms: int
    used: bool = False
    evidence_features: Optional[Dict[str, Any]] = None


class LivenessChallengeManager:
    """Strict liveness challenge/session manager with signed one-time ticket."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 45,
        max_cache_size: int = 2048,
        signing_key: str = "dev-liveness-signing-key",
        ticket_ttl_seconds: int = 180,
    ):
        self._ttl_ms = max(5, int(ttl_seconds)) * 1000
        self._ticket_ttl_ms = max(10, int(ticket_ttl_seconds)) * 1000
        self._max_cache_size = max(128, int(max_cache_size))
        self._signing_key = signing_key.encode("utf-8")
        self._lock = Lock()
        self._challenges: Dict[str, LivenessChallenge] = {}
        self._sessions: Dict[str, VerifiedLivenessSession] = {}

    def create_challenge(self) -> Dict[str, Any]:
        now_ms = _now_ms()
        expires_at_ms = now_ms + self._ttl_ms
        challenge_id = secrets.token_urlsafe(18)
        nonce = secrets.token_urlsafe(12)
        actions = self._build_actions()
        challenge = LivenessChallenge(
            challenge_id=challenge_id,
            nonce=nonce,
            actions=actions,
            issued_at_ms=now_ms,
            expires_at_ms=expires_at_ms,
        )

        with self._lock:
            self._prune(now_ms)
            self._challenges[challenge_id] = challenge
            self._trim_if_needed()

        return {
            "ok": True,
            "mode": "strict",
            "challenge_id": challenge_id,
            "nonce": nonce,
            "actions": actions,
            "issued_at_ms": now_ms,
            "expires_at_ms": expires_at_ms,
            "ttl_ms": self._ttl_ms,
        }

    def verify_proof(
        self,
        *,
        proof_raw: Optional[str],
        max_proof_age_seconds: int,
        min_duration_ms: int,
        max_duration_ms: int,
        min_motion_score: float,
        max_missing_frames: int,
        consume_challenge: bool = True,
    ) -> Dict[str, Any]:
        parsed = self._parse_proof(
            proof_raw=proof_raw,
            max_proof_age_seconds=max_proof_age_seconds,
            min_duration_ms=min_duration_ms,
            max_duration_ms=max_duration_ms,
            min_motion_score=min_motion_score,
            max_missing_frames=max_missing_frames,
        )
        if not parsed["ok"]:
            return parsed

        proof = parsed["proof"]
        challenge_result = self._verify_challenge(
            challenge_id=proof["challenge_id"],
            nonce=proof["nonce"],
            actions=proof["actions"],
            consume=consume_challenge,
        )
        if not challenge_result["ok"]:
            return challenge_result

        return {
            "ok": True,
            "mode": "strict",
            "challenge_id": proof["challenge_id"],
            "duration_ms": proof["duration_ms"],
            "actions": proof["actions"],
            "metrics": proof["metrics"],
        }

    def issue_ticket(
        self,
        *,
        challenge_id: str,
        key_image_hash: str,
        key_face_embedding: np.ndarray,
        anti_spoof_score: float,
        evidence_features: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now_ms = _now_ms()
        expires_at_ms = now_ms + self._ticket_ttl_ms
        session_id = secrets.token_urlsafe(16)
        session = VerifiedLivenessSession(
            session_id=session_id,
            challenge_id=challenge_id,
            key_image_hash=key_image_hash,
            key_face_embedding=np.asarray(key_face_embedding, dtype=np.float32).reshape(-1),
            anti_spoof_score=float(anti_spoof_score),
            issued_at_ms=now_ms,
            expires_at_ms=expires_at_ms,
            evidence_features=dict(evidence_features or {}),
        )
        payload = {
            "sid": session_id,
            "cid": challenge_id,
            "kh": key_image_hash,
            "as": round(float(anti_spoof_score), 6),
            "iat": now_ms,
            "exp": expires_at_ms,
        }
        token = self._encode_ticket(payload)

        with self._lock:
            self._prune(now_ms)
            self._sessions[session_id] = session
            self._trim_if_needed()

        return {
            "ok": True,
            "mode": "strict",
            "session_id": session_id,
            "issued_at_ms": now_ms,
            "expires_at_ms": expires_at_ms,
            "anti_spoof_score": float(anti_spoof_score),
            "liveness_ticket": token,
        }

    def consume_ticket(
        self,
        *,
        ticket: Optional[str],
        checkin_image_hash: str,
        checkin_face_embedding: np.ndarray,
        min_face_similarity: float,
    ) -> Dict[str, Any]:
        if not ticket or not ticket.strip():
            return {"ok": False, "reason": "缺少 liveness_ticket"}

        payload_result = self._decode_ticket(ticket.strip())
        if not payload_result["ok"]:
            return payload_result
        payload = payload_result["payload"]

        session_id = str(payload.get("sid") or "")
        claim_hash = str(payload.get("kh") or "")
        now_ms = _now_ms()

        if not session_id:
            return {"ok": False, "reason": "liveness_ticket 缺少 sid"}
        if claim_hash != checkin_image_hash:
            return {"ok": False, "reason": "签到图片与活体会话不一致（hash 不匹配）"}
        if _as_int(payload.get("exp"), 0) < now_ms:
            return {"ok": False, "reason": "liveness_ticket 已过期，请重新活体检测"}

        with self._lock:
            self._prune(now_ms)
            session = self._sessions.get(session_id)
            if session is None:
                return {"ok": False, "reason": "活体会话不存在或已过期"}
            if session.used:
                return {"ok": False, "reason": "活体会话已使用，禁止重放"}
            if session.expires_at_ms < now_ms:
                session.used = True
                return {"ok": False, "reason": "活体会话已过期，请重新检测"}
            if session.key_image_hash != checkin_image_hash:
                session.used = True
                return {"ok": False, "reason": "会话绑定校验失败（hash 不一致）"}

            current_embedding = np.asarray(checkin_face_embedding, dtype=np.float32).reshape(-1)
            bound_embedding = np.asarray(session.key_face_embedding, dtype=np.float32).reshape(-1)
            similarity = self._cosine_similarity(bound_embedding, current_embedding)
            if similarity < float(min_face_similarity):
                session.used = True
                return {
                    "ok": False,
                    "reason": f"会话绑定人脸不一致（{similarity:.3f} < {float(min_face_similarity):.3f}）",
                }

            session.used = True
            return {
                "ok": True,
                "mode": "strict",
                "session_id": session.session_id,
                "challenge_id": session.challenge_id,
                "anti_spoof_score": session.anti_spoof_score,
                "face_similarity": similarity,
                "issued_at_ms": session.issued_at_ms,
                "expires_at_ms": session.expires_at_ms,
                "evidence_features": dict(session.evidence_features or {}),
            }

    def _parse_proof(
        self,
        *,
        proof_raw: Optional[str],
        max_proof_age_seconds: int,
        min_duration_ms: int,
        max_duration_ms: int,
        min_motion_score: float,
        max_missing_frames: int,
    ) -> Dict[str, Any]:
        if not proof_raw or not proof_raw.strip():
            return {"ok": False, "reason": "缺少活体证明"}
        try:
            proof = json.loads(proof_raw)
        except json.JSONDecodeError:
            return {"ok": False, "reason": "活体证明格式错误（JSON 解析失败）"}
        if not isinstance(proof, dict):
            return {"ok": False, "reason": "活体证明格式错误（不是对象）"}

        challenge_id = str(proof.get("challenge_id") or "").strip()
        nonce = str(proof.get("nonce") or "").strip()
        actions = proof.get("actions")
        if not challenge_id:
            return {"ok": False, "reason": "活体证明缺少 challenge_id"}
        if not nonce:
            return {"ok": False, "reason": "活体证明缺少 nonce"}
        if not isinstance(actions, list) or not actions or any(not isinstance(item, str) for item in actions):
            return {"ok": False, "reason": "活体证明缺少有效动作序列"}

        started_at_ms = _as_int(proof.get("started_at_ms"), 0)
        passed_at_ms = _as_int(proof.get("passed_at_ms"), 0)
        duration_ms = _as_int(proof.get("duration_ms"), 0)
        if duration_ms <= 0 and started_at_ms > 0 and passed_at_ms >= started_at_ms:
            duration_ms = passed_at_ms - started_at_ms

        now_ms = _now_ms()
        max_age_ms = max(1, int(max_proof_age_seconds)) * 1000
        min_duration = max(300, int(min_duration_ms))
        max_duration = max(min_duration, int(max_duration_ms))

        if started_at_ms <= 0 or passed_at_ms <= 0:
            return {"ok": False, "reason": "活体时间戳缺失"}
        if passed_at_ms < started_at_ms:
            return {"ok": False, "reason": "活体时间戳非法"}
        if duration_ms < min_duration or duration_ms > max_duration:
            return {"ok": False, "reason": f"活体时长不在允许范围内（{duration_ms}ms）"}
        if passed_at_ms > now_ms + 10_000:
            return {"ok": False, "reason": "活体时间超前，疑似伪造"}
        if now_ms - passed_at_ms > max_age_ms:
            return {"ok": False, "reason": "活体结果已过期，请重新检测"}

        metrics = proof.get("metrics") if isinstance(proof.get("metrics"), dict) else {}
        motion_score = _as_float(metrics.get("motion_score"), 0.0)
        missing_frames = _as_int(metrics.get("missing_frames"), 0)
        blink_count = _as_int(metrics.get("blink_count"), 0)
        yaw_span = _as_float(metrics.get("yaw_span"), 0.0)
        mouth_peak_gain = _as_float(metrics.get("mouth_peak_gain"), 0.0)
        scale_peak_gain = _as_float(metrics.get("scale_peak_gain"), 0.0)
        max_freeze_run = _as_int(metrics.get("max_freeze_run"), 0)

        if motion_score < float(min_motion_score):
            return {"ok": False, "reason": "运动变化不足，疑似重放"}
        if missing_frames > int(max_missing_frames):
            return {"ok": False, "reason": "跟踪中断次数过多，活体验证失败"}
        if blink_count < 1:
            return {"ok": False, "reason": "严格活体要求至少一次有效眨眼"}
        if yaw_span < 0.16:
            return {"ok": False, "reason": "头部转动幅度不足"}
        if mouth_peak_gain < 0.014 and scale_peak_gain < 0.007:
            return {"ok": False, "reason": "嘴部/距离动作变化不足"}
        if max_freeze_run > 28:
            return {"ok": False, "reason": "画面连续静止，疑似重放"}

        return {
            "ok": True,
            "proof": {
                "challenge_id": challenge_id,
                "nonce": nonce,
                "actions": list(actions),
                "started_at_ms": started_at_ms,
                "passed_at_ms": passed_at_ms,
                "duration_ms": duration_ms,
                "metrics": {
                    "motion_score": motion_score,
                    "missing_frames": missing_frames,
                    "blink_count": blink_count,
                    "yaw_span": yaw_span,
                    "mouth_peak_gain": mouth_peak_gain,
                    "scale_peak_gain": scale_peak_gain,
                    "max_freeze_run": max_freeze_run,
                },
            },
        }

    def _verify_challenge(
        self,
        *,
        challenge_id: str,
        nonce: str,
        actions: List[str],
        consume: bool,
    ) -> Dict[str, Any]:
        now_ms = _now_ms()
        with self._lock:
            self._prune(now_ms)
            challenge = self._challenges.get(challenge_id)
            if challenge is None:
                return {"ok": False, "reason": "活体挑战不存在或已过期"}
            if challenge.used:
                return {"ok": False, "reason": "活体挑战已被使用，请重新检测"}
            if challenge.expires_at_ms < now_ms:
                challenge.used = True
                return {"ok": False, "reason": "活体挑战已过期，请重新检测"}
            if nonce != challenge.nonce:
                challenge.used = True
                return {"ok": False, "reason": "活体挑战 nonce 不匹配"}
            if actions != challenge.actions:
                challenge.used = True
                return {"ok": False, "reason": "活体动作顺序不匹配"}
            if consume:
                challenge.used = True
        return {"ok": True}

    def _encode_ticket(self, payload: Dict[str, Any]) -> str:
        payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        payload_b64 = _b64url_encode(payload_json)
        signature = hmac.new(self._signing_key, payload_b64.encode("ascii"), digestmod="sha256").digest()
        sig_b64 = _b64url_encode(signature)
        return f"{payload_b64}.{sig_b64}"

    def _decode_ticket(self, token: str) -> Dict[str, Any]:
        parts = token.split(".")
        if len(parts) != 2:
            return {"ok": False, "reason": "liveness_ticket 格式错误"}
        payload_b64, sig_b64 = parts
        expected = hmac.new(self._signing_key, payload_b64.encode("ascii"), digestmod="sha256").digest()
        try:
            provided = _b64url_decode(sig_b64)
        except Exception:
            return {"ok": False, "reason": "liveness_ticket 签名编码错误"}
        if not hmac.compare_digest(expected, provided):
            return {"ok": False, "reason": "liveness_ticket 签名无效"}
        try:
            payload_bytes = _b64url_decode(payload_b64)
            payload = json.loads(payload_bytes.decode("utf-8"))
        except Exception:
            return {"ok": False, "reason": "liveness_ticket 载荷解析失败"}
        if not isinstance(payload, dict):
            return {"ok": False, "reason": "liveness_ticket 载荷非法"}
        return {"ok": True, "payload": payload}

    def _build_actions(self) -> List[str]:
        actions = list(_STRICT_ACTION_POOL)
        secrets.SystemRandom().shuffle(actions)
        return actions

    def _prune(self, now_ms: int) -> None:
        expired_challenges: List[str] = []
        for key, item in self._challenges.items():
            if item.expires_at_ms < now_ms or (item.used and now_ms - item.expires_at_ms > self._ttl_ms):
                expired_challenges.append(key)
        for key in expired_challenges:
            self._challenges.pop(key, None)

        expired_sessions: List[str] = []
        for key, item in self._sessions.items():
            if item.expires_at_ms < now_ms or (item.used and now_ms - item.expires_at_ms > self._ticket_ttl_ms):
                expired_sessions.append(key)
        for key in expired_sessions:
            self._sessions.pop(key, None)

    def _trim_if_needed(self) -> None:
        if len(self._challenges) > self._max_cache_size:
            challenge_items = sorted(self._challenges.items(), key=lambda pair: pair[1].issued_at_ms)
            overflow = len(challenge_items) - self._max_cache_size
            for idx in range(max(0, overflow)):
                self._challenges.pop(challenge_items[idx][0], None)
        if len(self._sessions) > self._max_cache_size:
            session_items = sorted(self._sessions.items(), key=lambda pair: pair[1].issued_at_ms)
            overflow = len(session_items) - self._max_cache_size
            for idx in range(max(0, overflow)):
                self._sessions.pop(session_items[idx][0], None)

    @staticmethod
    def sha256_hex(data: bytes) -> str:
        return sha256(data).hexdigest()

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        a_vec = np.asarray(a, dtype=np.float32).reshape(-1)
        b_vec = np.asarray(b, dtype=np.float32).reshape(-1)
        a_norm = float(np.linalg.norm(a_vec))
        b_norm = float(np.linalg.norm(b_vec))
        if a_norm <= 0 or b_norm <= 0:
            return 0.0
        return float(np.dot(a_vec / a_norm, b_vec / b_norm))
