from __future__ import annotations

from collections import OrderedDict
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import base64
import hashlib
import math
import secrets
import sqlite3
import time

import cv2
import numpy as np

from config import DB_PATH, ensure_directories
from face_model import get_face_app
from vector_index import VectorSearchIndex


def _read_image(path: Path) -> Optional[np.ndarray]:
    try:
        raw = np.fromfile(str(path), dtype=np.uint8)
    except Exception:
        return None
    if raw.size == 0:
        return None
    return cv2.imdecode(raw, cv2.IMREAD_COLOR)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _password_hash(password: str, *, iterations: int = 260_000) -> str:
    text = str(password or "")
    if not text:
        raise ValueError("password 不能为空")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", text.encode("utf-8"), salt, iterations)
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
    digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${iterations}${salt_b64}${digest_b64}"


def _password_verify(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_b64, digest_b64 = str(encoded or "").split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = max(1, int(iterations_text))
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
    except Exception:
        return False

    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        salt,
        iterations,
    )
    return secrets.compare_digest(candidate, expected)


class FaceDB:
    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        face_app: Any = None,
        *,
        vector_backend: str = "auto",
        enable_embedding_cache: bool = True,
        query_embedding_cache_size: int = 256,
        vector_candidate_multiplier: int = 8,
        vector_annoy_trees: int = 20,
    ):
        raw_db_path = str(db_path or DB_PATH)
        self._use_memory_db = raw_db_path == ":memory:"
        self._memory_conn: Optional[sqlite3.Connection] = None

        if self._use_memory_db:
            self.db_path: Union[str, Path] = ":memory:"
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._memory_conn.row_factory = sqlite3.Row
        else:
            self.db_path = Path(raw_db_path).resolve()
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        ensure_directories()

        # 延迟初始化模型，只有在需要从图片提特征时才加载
        self.app = face_app

        self._enable_embedding_cache = bool(enable_embedding_cache)
        self._embedding_cache: Dict[int, np.ndarray] = {}
        self._face_meta_cache: Dict[int, Dict[str, Any]] = {}

        self._query_embedding_cache_size = max(0, int(query_embedding_cache_size))
        self._query_embedding_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

        self._vector_index = VectorSearchIndex(
            dim=512,
            backend=vector_backend,
            annoy_trees=vector_annoy_trees,
            candidate_multiplier=vector_candidate_multiplier,
        )

        self.create_tables()
        self._reload_face_cache_and_index()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self):
        if self._use_memory_db:
            if self._memory_conn is None:
                raise RuntimeError("内存数据库连接未初始化")
            yield self._memory_conn
        else:
            with closing(self._connect()) as conn:
                yield conn

    def create_tables(self) -> None:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS faces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_name TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    image_path TEXT NOT NULL,
                    user_id INTEGER,
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS checkin_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_name TEXT,
                    matched_face_id INTEGER,
                    similarity REAL,
                    status TEXT NOT NULL,
                    reason TEXT,
                    capture_image_path TEXT NOT NULL,
                    matched_image_path TEXT,
                    lat REAL,
                    lng REAL,
                    center_lat REAL,
                    center_lng REAL,
                    radius_m REAL,
                    distance_m REAL,
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_faces_person_name ON faces(person_name)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_checkin_records_create_time ON checkin_records(create_time DESC)"
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    display_name TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS teacher_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token TEXT NOT NULL UNIQUE,
                    expires_at_ms INTEGER NOT NULL,
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_name TEXT NOT NULL,
                    course_code TEXT NOT NULL UNIQUE,
                    teacher_user_id INTEGER NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS attendance_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_id INTEGER NOT NULL,
                    teacher_user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    start_time_ms INTEGER NOT NULL,
                    end_time_ms INTEGER NOT NULL,
                    geofence_enabled INTEGER NOT NULL DEFAULT 0,
                    center_lat REAL,
                    center_lng REAL,
                    radius_m REAL,
                    face_threshold REAL NOT NULL DEFAULT 0.6,
                    top_k INTEGER NOT NULL DEFAULT 1,
                    strict_liveness_required INTEGER NOT NULL DEFAULT 0,
                    strict_liveness_full_actions INTEGER NOT NULL DEFAULT 0,
                    checkin_once INTEGER NOT NULL DEFAULT 1,
                    qr_token TEXT NOT NULL UNIQUE,
                    qr_expires_at_ms INTEGER NOT NULL,
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closed_time TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS attendance_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    person_name TEXT,
                    matched_face_id INTEGER,
                    matched_user_id INTEGER,
                    similarity REAL,
                    status TEXT NOT NULL,
                    reason TEXT,
                    capture_image_path TEXT,
                    lat REAL,
                    lng REAL,
                    distance_m REAL,
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_teacher_tokens_token ON teacher_tokens(token)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_courses_teacher ON courses(teacher_user_id)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_attendance_sessions_teacher ON attendance_sessions(teacher_user_id, create_time DESC)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_attendance_sessions_qr_token ON attendance_sessions(qr_token)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_attendance_records_session ON attendance_records(session_id, create_time DESC)"
            )
            self._run_schema_migrations(conn)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_faces_user_id ON faces(user_id)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_attendance_records_user ON attendance_records(matched_user_id, create_time DESC)"
            )
            conn.commit()
            self._ensure_default_teacher_and_course(conn)

    def _run_schema_migrations(self, conn: sqlite3.Connection) -> None:
        face_columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(faces)").fetchall()}
        if "user_id" not in face_columns:
            conn.execute("ALTER TABLE faces ADD COLUMN user_id INTEGER")

        attendance_columns = {
            str(row["name"]) for row in conn.execute("PRAGMA table_info(attendance_records)").fetchall()
        }
        if "matched_user_id" not in attendance_columns:
            conn.execute("ALTER TABLE attendance_records ADD COLUMN matched_user_id INTEGER")

        session_columns = {
            str(row["name"]) for row in conn.execute("PRAGMA table_info(attendance_sessions)").fetchall()
        }
        if "strict_liveness_full_actions" not in session_columns:
            conn.execute(
                "ALTER TABLE attendance_sessions ADD COLUMN strict_liveness_full_actions INTEGER NOT NULL DEFAULT 0"
            )

    def _ensure_default_teacher_and_course(self, conn: sqlite3.Connection) -> None:
        teacher_row = conn.execute(
            """
            SELECT id, username, role
            FROM users
            WHERE role IN ('teacher', 'admin')
            ORDER BY id ASC
            LIMIT 1
            """
        ).fetchone()

        if teacher_row is None:
            password_hash = _password_hash("teacher123")
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO users (username, password_hash, role, display_name, is_active)
                VALUES (?, ?, ?, ?, 1)
                """,
                ("teacher", password_hash, "teacher", "默认教师"),
            )
            teacher_id = int(cursor.lastrowid)
        else:
            teacher_id = int(teacher_row["id"])

        course_count_row = conn.execute("SELECT COUNT(*) AS cnt FROM courses").fetchone()
        course_count = int(course_count_row["cnt"]) if course_count_row else 0
        if course_count <= 0:
            conn.execute(
                """
                INSERT INTO courses (course_name, course_code, teacher_user_id, is_active)
                VALUES (?, ?, ?, 1)
                """,
                ("演示课程", "DEMO101", teacher_id),
            )

        conn.commit()

    def _ensure_face_app(self) -> Any:
        if self.app is None:
            self.app = get_face_app(det_size=(640, 640))
        return self.app

    def _build_query_cache_key(self, file_path: Path) -> str:
        resolved = file_path.resolve()
        try:
            stat = resolved.stat()
            return f"{resolved}::{stat.st_mtime_ns}::{stat.st_size}"
        except Exception:
            return str(resolved)

    def _get_cached_query_analysis(self, key: str) -> Optional[Dict[str, Any]]:
        if self._query_embedding_cache_size <= 0:
            return None
        cached = self._query_embedding_cache.get(key)
        if cached is None:
            return None
        self._query_embedding_cache.move_to_end(key)
        return {
            "embedding": np.asarray(cached["embedding"], dtype=np.float32).copy(),
            "face_detect": dict(cached["face_detect"]),
        }

    def _put_cached_query_analysis(self, key: str, embedding: np.ndarray, face_detect: Dict[str, Any]) -> None:
        if self._query_embedding_cache_size <= 0:
            return
        self._query_embedding_cache[key] = {
            "embedding": np.asarray(embedding, dtype=np.float32).copy(),
            "face_detect": dict(face_detect),
        }
        self._query_embedding_cache.move_to_end(key)
        while len(self._query_embedding_cache) > self._query_embedding_cache_size:
            self._query_embedding_cache.popitem(last=False)

    def _face_area(self, face: Any) -> float:
        bbox = getattr(face, "bbox", None)
        if bbox is None:
            return -1.0
        try:
            x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
            return max(0.0, x2 - x1) * max(0.0, y2 - y1)
        except Exception:
            return -1.0

    def _face_bbox(self, face: Any) -> Optional[List[float]]:
        bbox = getattr(face, "bbox", None)
        if bbox is None:
            return None
        try:
            x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
            return [x1, y1, x2, y2]
        except Exception:
            return None

    def _select_primary_face(self, faces: List[Any]) -> Tuple[Any, int]:
        if len(faces) == 1:
            return faces[0], 0

        best_idx = 0
        best_area = self._face_area(faces[0])
        for idx in range(1, len(faces)):
            area = self._face_area(faces[idx])
            if area > best_area:
                best_idx = idx
                best_area = area
        return faces[best_idx], best_idx

    def _analyze_image_face(self, image_path: Union[str, Path]) -> Dict[str, Any]:
        file_path = Path(image_path).resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"图像文件不存在: {file_path}")

        cache_key = self._build_query_cache_key(file_path)
        cached = self._get_cached_query_analysis(cache_key)
        if cached is not None:
            return cached

        img = _read_image(file_path)
        if img is None:
            raise ValueError(f"无法读取图像文件: {file_path}")
        analyzed = self.analyze_face_array(img, source=str(file_path))
        embedding = np.asarray(analyzed["embedding"], dtype=np.float32)
        face_detect = dict(analyzed["face_detect"])
        self._put_cached_query_analysis(cache_key, embedding, face_detect)
        return {"embedding": embedding, "face_detect": face_detect}

    def analyze_face_array(self, image: np.ndarray, *, source: str = "image") -> Dict[str, Any]:
        if image is None or image.size == 0:
            raise ValueError("输入图像为空")
        app = self._ensure_face_app()
        faces = app.get(image)
        if not faces:
            raise ValueError(f"在图像中未检测到人脸: {source}")

        selected_face, selected_index = self._select_primary_face(list(faces))
        embedding = np.asarray(selected_face.embedding, dtype=np.float32).reshape(-1)
        face_count = len(faces)
        selected_bbox = self._face_bbox(selected_face)
        face_detect = {
            "face_count": face_count,
            "selected_strategy": "largest_bbox",
            "selected_face_index": selected_index,
            "selected_face_bbox": selected_bbox,
            "multiple_faces": face_count > 1,
            "warning": "检测到多张人脸，已自动选择最大人脸进行识别" if face_count > 1 else None,
        }
        return {"embedding": embedding, "face_detect": face_detect}

    def analyze_face_bytes(self, image_bytes: bytes, *, source: str = "bytes") -> Dict[str, Any]:
        if not image_bytes:
            raise ValueError("图像字节为空")
        raw = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("无法解码图像字节")
        return self.analyze_face_array(image, source=source)

    def _extract_embedding_from_image(self, image_path: Union[str, Path]) -> np.ndarray:
        analyzed = self._analyze_image_face(image_path)
        return np.asarray(analyzed["embedding"], dtype=np.float32)

    def analyze_face_image(self, image_path: Union[str, Path]) -> Dict[str, Any]:
        analyzed = self._analyze_image_face(image_path)
        return {
            "embedding": np.asarray(analyzed["embedding"], dtype=np.float32),
            "face_detect": dict(analyzed["face_detect"]),
        }

    def _normalize_store_path(self, image_path: Union[str, Path]) -> str:
        if isinstance(image_path, Path):
            return str(image_path.resolve())
        text = str(image_path).strip()
        if text.startswith("embedded://"):
            return text
        return str(Path(text).resolve())

    def _load_faces_for_search(self) -> List[sqlite3.Row]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT id, person_name, embedding, image_path, user_id, create_time FROM faces"
            ).fetchall()
        return rows

    def _reload_face_cache_and_index(self) -> None:
        rows = self._load_faces_for_search()

        self._face_meta_cache = {
            int(row["id"]): {
                "face_id": int(row["id"]),
                "person_name": str(row["person_name"]),
                "image_path": row["image_path"],
                "user_id": row["user_id"],
                "create_time": row["create_time"],
            }
            for row in rows
        }

        if not self._enable_embedding_cache:
            self._embedding_cache.clear()
            self._vector_index.clear()
            return

        self._embedding_cache = {
            int(row["id"]): np.frombuffer(row["embedding"], dtype=np.float32)
            for row in rows
        }
        self._vector_index.rebuild(self._embedding_cache.items())

    def add_face(
        self,
        person_name: str,
        image_path: Union[str, Path],
        *,
        user_id: Optional[int] = None,
    ) -> int:
        resolved_path = Path(image_path).resolve()
        embedding = self._extract_embedding_from_image(resolved_path)
        return self.add_face_embedding(
            person_name=person_name,
            embedding=embedding,
            image_path=resolved_path,
            user_id=user_id,
        )

    def add_face_with_analysis(
        self,
        person_name: str,
        image_path: Union[str, Path],
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        resolved_path = Path(image_path).resolve()
        analyzed = self._analyze_image_face(resolved_path)
        face_id = self.add_face_embedding(
            person_name=person_name,
            embedding=np.asarray(analyzed["embedding"], dtype=np.float32),
            image_path=resolved_path,
            user_id=user_id,
        )
        return {"face_id": face_id, "face_detect": dict(analyzed["face_detect"])}

    def add_face_embedding(
        self,
        *,
        person_name: str,
        embedding: np.ndarray,
        image_path: Union[str, Path],
        user_id: Optional[int] = None,
    ) -> int:
        if not person_name.strip():
            raise ValueError("person_name 不能为空")

        embedding_np = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if embedding_np.size == 0:
            raise ValueError("embedding 不能为空")

        store_path = self._normalize_store_path(image_path)

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO faces (person_name, embedding, image_path, user_id) VALUES (?, ?, ?, ?)",
                (person_name.strip(), embedding_np.tobytes(), store_path, int(user_id) if user_id is not None else None),
            )
            conn.commit()
            face_id = int(cursor.lastrowid)

        meta = {
            "face_id": face_id,
            "person_name": person_name.strip(),
            "image_path": store_path,
            "user_id": int(user_id) if user_id is not None else None,
            "create_time": None,
        }
        self._face_meta_cache[face_id] = meta

        if self._enable_embedding_cache:
            self._embedding_cache[face_id] = embedding_np
            self._vector_index.upsert(face_id, embedding_np)

        return face_id

    def add_face_embeddings_batch(
        self,
        records: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not records:
            return {"ok": True, "inserted": 0, "face_ids": []}

        prepared: List[Tuple[str, np.ndarray, str, Optional[int]]] = []
        for item in records:
            person_name = str(item.get("person_name", "")).strip()
            if not person_name:
                raise ValueError("批量写入中存在空 person_name")
            if "embedding" not in item:
                raise ValueError("批量写入中缺少 embedding")
            embedding_np = np.asarray(item["embedding"], dtype=np.float32).reshape(-1)
            if embedding_np.size == 0:
                raise ValueError("批量写入中存在空 embedding")
            image_path = item.get("image_path") or f"embedded://{person_name}"
            user_id = item.get("user_id")
            prepared.append(
                (
                    person_name,
                    embedding_np,
                    self._normalize_store_path(image_path),
                    int(user_id) if user_id is not None else None,
                )
            )

        face_ids: List[int] = []
        with self._connection() as conn:
            cursor = conn.cursor()
            for person_name, embedding_np, image_path, user_id in prepared:
                cursor.execute(
                    "INSERT INTO faces (person_name, embedding, image_path, user_id) VALUES (?, ?, ?, ?)",
                    (person_name, embedding_np.tobytes(), image_path, user_id),
                )
                face_ids.append(int(cursor.lastrowid))
            conn.commit()

        for face_id, (person_name, embedding_np, image_path, user_id) in zip(face_ids, prepared):
            self._face_meta_cache[face_id] = {
                "face_id": face_id,
                "person_name": person_name,
                "image_path": image_path,
                "user_id": user_id,
                "create_time": None,
            }
            if self._enable_embedding_cache:
                self._embedding_cache[face_id] = embedding_np
                self._vector_index.upsert(face_id, embedding_np)

        return {"ok": True, "inserted": len(face_ids), "face_ids": face_ids}

    def _search_face_sqlite_scan(
        self,
        query_embedding: np.ndarray,
        *,
        top_k: int,
        threshold: float,
    ) -> List[Dict[str, Any]]:
        query_embedding = np.asarray(query_embedding, dtype=np.float32).reshape(-1)
        query_norm = float(np.linalg.norm(query_embedding))
        if query_norm == 0:
            raise ValueError("特征向量无效")
        query_unit = query_embedding / query_norm

        with self._connection() as conn:
            rows = conn.execute(
                "SELECT id, person_name, embedding, image_path, user_id, create_time FROM faces"
            ).fetchall()

        candidates: List[Dict[str, Any]] = []
        for row in rows:
            db_embedding = np.frombuffer(row["embedding"], dtype=np.float32)
            db_norm = float(np.linalg.norm(db_embedding))
            if db_norm == 0:
                continue
            similarity = float(np.dot(query_unit, db_embedding / db_norm))
            if similarity >= threshold:
                candidates.append(
                    {
                        "face_id": int(row["id"]),
                        "person_name": str(row["person_name"]),
                        "similarity": similarity,
                        "image_path": row["image_path"],
                        "user_id": row["user_id"],
                        "create_time": row["create_time"],
                    }
                )

        candidates.sort(key=lambda item: item["similarity"], reverse=True)
        return candidates[:top_k]

    def _search_face_with_index(
        self,
        query_embedding: np.ndarray,
        *,
        top_k: int,
        threshold: float,
    ) -> List[Dict[str, Any]]:
        hits = self._vector_index.search(query_embedding, top_k=top_k, threshold=threshold)
        results: List[Dict[str, Any]] = []
        for hit in hits:
            meta = self._face_meta_cache.get(hit.face_id)
            if not meta:
                continue
            results.append(
                {
                    "face_id": int(meta["face_id"]),
                    "person_name": str(meta["person_name"]),
                    "similarity": float(hit.similarity),
                    "image_path": meta["image_path"],
                    "user_id": meta.get("user_id"),
                    "create_time": meta.get("create_time"),
                }
            )
        results.sort(key=lambda item: item["similarity"], reverse=True)
        return results[:top_k]

    def search_face(
        self,
        image_path: Optional[Union[str, Path]] = None,
        embedding: Optional[np.ndarray] = None,
        top_k: int = 5,
        threshold: float = 0.5,
    ) -> List[Dict[str, Any]]:
        if top_k <= 0:
            raise ValueError("top_k 必须大于 0")

        if image_path is not None:
            embedding = self._extract_embedding_from_image(image_path)

        if embedding is None:
            raise ValueError("必须提供图像路径或特征向量")

        query_embedding = np.asarray(embedding, dtype=np.float32).reshape(-1)
        query_norm = float(np.linalg.norm(query_embedding))
        if query_norm == 0:
            raise ValueError("特征向量无效")

        if self._enable_embedding_cache and len(self._vector_index) > 0:
            try:
                return self._search_face_with_index(
                    query_embedding,
                    top_k=top_k,
                    threshold=threshold,
                )
            except Exception:
                # 向量索引异常时回退到 SQLite 扫描
                pass

        return self._search_face_sqlite_scan(
            query_embedding,
            top_k=top_k,
            threshold=threshold,
        )

    def search_face_with_analysis(
        self,
        *,
        image_path: Union[str, Path],
        top_k: int = 5,
        threshold: float = 0.5,
    ) -> Dict[str, Any]:
        analyzed = self._analyze_image_face(image_path)
        results = self.search_face(
            embedding=np.asarray(analyzed["embedding"], dtype=np.float32),
            top_k=top_k,
            threshold=threshold,
        )
        return {"results": results, "face_detect": dict(analyzed["face_detect"])}

    def get_all_faces(self, limit: int = 100) -> List[Dict[str, Any]]:
        query = "SELECT id, person_name, image_path, user_id, create_time FROM faces ORDER BY id DESC LIMIT ?"
        with self._connection() as conn:
            rows = conn.execute(query, (limit,)).fetchall()

        return [
            {
                "face_id": int(row["id"]),
                "person_name": row["person_name"],
                "image_path": row["image_path"],
                "user_id": row["user_id"],
                "create_time": row["create_time"],
            }
            for row in rows
        ]

    def get_vector_index_stats(self) -> Dict[str, Any]:
        payload = dict(self._vector_index.stats())
        payload.update(
            {
                "embedding_cache_enabled": self._enable_embedding_cache,
                "embedding_cache_size": len(self._embedding_cache),
                "query_cache_size": self._query_embedding_cache_size,
                "query_cache_items": len(self._query_embedding_cache),
            }
        )
        return payload

    def add_checkin_record(
        self,
        *,
        capture_image_path: Union[str, Path],
        status: str,
        reason: Optional[str] = None,
        person_name: Optional[str] = None,
        matched_face_id: Optional[int] = None,
        similarity: Optional[float] = None,
        matched_image_path: Optional[Union[str, Path]] = None,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        center_lat: Optional[float] = None,
        center_lng: Optional[float] = None,
        radius_m: Optional[float] = None,
        distance_m: Optional[float] = None,
    ) -> int:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO checkin_records (
                    person_name, matched_face_id, similarity, status, reason,
                    capture_image_path, matched_image_path, lat, lng,
                    center_lat, center_lng, radius_m, distance_m
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    person_name,
                    matched_face_id,
                    similarity,
                    status,
                    reason,
                    str(Path(capture_image_path).resolve()),
                    str(Path(matched_image_path).resolve()) if matched_image_path else None,
                    lat,
                    lng,
                    center_lat,
                    center_lng,
                    radius_m,
                    distance_m,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def get_recent_checkins(self, limit: int = 20) -> List[Dict[str, Any]]:
        query = """
            SELECT
                id, person_name, matched_face_id, similarity, status, reason,
                capture_image_path, matched_image_path, lat, lng,
                center_lat, center_lng, radius_m, distance_m, create_time
            FROM checkin_records
            ORDER BY id DESC
            LIMIT ?
        """
        with self._connection() as conn:
            rows = conn.execute(query, (limit,)).fetchall()

        return self._serialize_checkin_rows(rows)

    def _serialize_checkin_rows(self, rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
        return [
            {
                "checkin_id": int(row["id"]),
                "person_name": row["person_name"],
                "matched_face_id": row["matched_face_id"],
                "similarity": row["similarity"],
                "status": row["status"],
                "reason": row["reason"],
                "capture_image_path": row["capture_image_path"],
                "matched_image_path": row["matched_image_path"],
                "lat": row["lat"],
                "lng": row["lng"],
                "center_lat": row["center_lat"],
                "center_lng": row["center_lng"],
                "radius_m": row["radius_m"],
                "distance_m": row["distance_m"],
                "create_time": row["create_time"],
            }
            for row in rows
        ]

    def get_checkins_by_person(self, person_name: str, limit: int = 100) -> List[Dict[str, Any]]:
        query = """
            SELECT
                id, person_name, matched_face_id, similarity, status, reason,
                capture_image_path, matched_image_path, lat, lng,
                center_lat, center_lng, radius_m, distance_m, create_time
            FROM checkin_records
            WHERE person_name = ?
            ORDER BY id DESC
            LIMIT ?
        """
        with self._connection() as conn:
            rows = conn.execute(query, (person_name, limit)).fetchall()
        return self._serialize_checkin_rows(rows)

    def get_checkins_for_export(
        self,
        *,
        person_name: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        base_query = """
            SELECT
                id, person_name, matched_face_id, similarity, status, reason,
                capture_image_path, matched_image_path, lat, lng,
                center_lat, center_lng, radius_m, distance_m, create_time
            FROM checkin_records
        """
        where_parts: List[str] = []
        params: List[Any] = []
        if person_name:
            where_parts.append("person_name = ?")
            params.append(person_name)
        if status:
            where_parts.append("status = ?")
            params.append(status)

        if where_parts:
            base_query += " WHERE " + " AND ".join(where_parts)

        base_query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self._connection() as conn:
            rows = conn.execute(base_query, tuple(params)).fetchall()
        return self._serialize_checkin_rows(rows)

    def delete_face(self, face_id: int, remove_image: bool = True) -> Dict[str, Any]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id, person_name, image_path, user_id FROM faces WHERE id = ?",
                (face_id,),
            ).fetchone()

            if row is None:
                raise ValueError(f"未找到 face_id={face_id} 的人脸记录")

            image_path = row["image_path"]
            conn.execute("DELETE FROM faces WHERE id = ?", (face_id,))
            conn.commit()

        self._face_meta_cache.pop(int(row["id"]), None)
        if self._enable_embedding_cache:
            self._embedding_cache.pop(int(row["id"]), None)
            self._vector_index.delete(int(row["id"]))

        image_deleted = False
        if remove_image and image_path and not str(image_path).startswith("embedded://"):
            image_file = Path(image_path)
            if image_file.exists():
                try:
                    image_file.unlink(missing_ok=True)
                    image_deleted = True
                except Exception:
                    image_deleted = False

        return {
            "face_id": int(row["id"]),
            "person_name": row["person_name"],
            "image_path": image_path,
            "user_id": row["user_id"],
            "image_deleted": image_deleted,
        }

    def _haversine_distance_m(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        r = 6371000.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = phi2 - phi1
        dlambda = math.radians(lng2 - lng1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))

    def suggest_geofence_from_history(
        self,
        *,
        person_name: Optional[str] = None,
        min_samples: int = 3,
        max_points: int = 500,
        cluster_distance_m: float = 120.0,
    ) -> Dict[str, Any]:
        query = """
            SELECT lat, lng, create_time
            FROM checkin_records
            WHERE status = 'success'
              AND lat IS NOT NULL
              AND lng IS NOT NULL
        """
        params: List[Any] = []
        if person_name:
            query += " AND person_name = ?"
            params.append(person_name)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(max_points)

        with self._connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        points = [
            {"lat": float(row["lat"]), "lng": float(row["lng"]), "create_time": row["create_time"]}
            for row in rows
        ]
        total_points = len(points)
        if total_points < min_samples:
            return {
                "ok": False,
                "reason": f"有效签到点不足，至少需要 {min_samples} 条",
                "person_name": person_name,
                "total_points": total_points,
            }

        clusters: List[Dict[str, Any]] = []
        for point in points:
            target_cluster = None
            nearest_distance = None
            for cluster in clusters:
                dist = self._haversine_distance_m(
                    point["lat"],
                    point["lng"],
                    cluster["center_lat"],
                    cluster["center_lng"],
                )
                if dist <= cluster_distance_m and (nearest_distance is None or dist < nearest_distance):
                    nearest_distance = dist
                    target_cluster = cluster

            if target_cluster is None:
                clusters.append(
                    {
                        "points": [point],
                        "center_lat": point["lat"],
                        "center_lng": point["lng"],
                        "latest_time": point["create_time"],
                    }
                )
                continue

            target_cluster["points"].append(point)
            point_count = len(target_cluster["points"])
            target_cluster["center_lat"] = (
                target_cluster["center_lat"] * (point_count - 1) + point["lat"]
            ) / point_count
            target_cluster["center_lng"] = (
                target_cluster["center_lng"] * (point_count - 1) + point["lng"]
            ) / point_count
            if point["create_time"] > target_cluster["latest_time"]:
                target_cluster["latest_time"] = point["create_time"]

        clusters.sort(key=lambda item: (len(item["points"]), item["latest_time"]), reverse=True)
        best_cluster = clusters[0]
        if len(best_cluster["points"]) < min_samples:
            return {
                "ok": False,
                "reason": f"聚类后无满足最小样本数的簇，当前最大簇样本 {len(best_cluster['points'])}",
                "person_name": person_name,
                "total_points": total_points,
                "cluster_count": len(clusters),
            }

        distances = [
            self._haversine_distance_m(
                p["lat"],
                p["lng"],
                best_cluster["center_lat"],
                best_cluster["center_lng"],
            )
            for p in best_cluster["points"]
        ]
        percentile_90 = float(np.percentile(np.asarray(distances, dtype=np.float32), 90))
        suggested_radius_m = max(80.0, min(500.0, percentile_90 + 20.0))

        return {
            "ok": True,
            "person_name": person_name,
            "total_points": total_points,
            "cluster_count": len(clusters),
            "cluster_size": len(best_cluster["points"]),
            "center_lat": float(best_cluster["center_lat"]),
            "center_lng": float(best_cluster["center_lng"]),
            "radius_m": float(suggested_radius_m),
            "distance_p90_m": percentile_90,
            "latest_time": best_cluster["latest_time"],
        }

    def _serialize_user_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "user_id": int(row["id"]),
            "username": str(row["username"]),
            "role": str(row["role"]),
            "display_name": row["display_name"] or row["username"],
            "is_active": bool(int(row["is_active"])),
            "create_time": row["create_time"],
        }

    def create_user(
        self,
        *,
        username: str,
        password: str,
        role: str = "teacher",
        display_name: Optional[str] = None,
        is_active: bool = True,
    ) -> Dict[str, Any]:
        username_text = str(username or "").strip()
        if not username_text:
            raise ValueError("username 不能为空")
        role_text = str(role or "").strip().lower() or "teacher"
        if role_text not in {"teacher", "student", "admin", "user"}:
            raise ValueError("role 非法")
        password_hash = _password_hash(password)
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO users (username, password_hash, role, display_name, is_active)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    username_text,
                    password_hash,
                    role_text,
                    (display_name or "").strip() or username_text,
                    1 if is_active else 0,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT id, username, role, display_name, is_active, create_time FROM users WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            if row is None:
                raise RuntimeError("创建用户失败")
            return self._serialize_user_row(row)

    def get_user_by_id(self, *, user_id: int) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT id, username, role, display_name, is_active, create_time
                FROM users
                WHERE id = ?
                LIMIT 1
                """,
                (int(user_id),),
            ).fetchone()
        if row is None:
            return None
        return self._serialize_user_row(row)

    def update_user_display_name(self, *, user_id: int, display_name: str) -> Dict[str, Any]:
        name_text = str(display_name or "").strip()
        if not name_text:
            raise ValueError("display_name 不能为空")
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE users
                SET display_name = ?
                WHERE id = ?
                """,
                (name_text, int(user_id)),
            )
            conn.commit()
            if cursor.rowcount <= 0:
                raise ValueError("用户不存在")
            row = conn.execute(
                """
                SELECT id, username, role, display_name, is_active, create_time
                FROM users
                WHERE id = ?
                LIMIT 1
                """,
                (int(user_id),),
            ).fetchone()
        if row is None:
            raise RuntimeError("更新用户昵称失败")
        return self._serialize_user_row(row)

    def count_user_faces(self, *, user_id: int) -> int:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM faces WHERE user_id = ?",
                (int(user_id),),
            ).fetchone()
        return int(row["cnt"]) if row else 0

    def list_user_faces(self, *, user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT id, person_name, image_path, user_id, create_time
                FROM faces
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(user_id), max(1, int(limit))),
            ).fetchall()
        return [
            {
                "face_id": int(row["id"]),
                "person_name": row["person_name"],
                "image_path": row["image_path"],
                "user_id": row["user_id"],
                "create_time": row["create_time"],
            }
            for row in rows
        ]

    def delete_faces_by_user(self, *, user_id: int, remove_image: bool = True) -> Dict[str, Any]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT id, image_path FROM faces WHERE user_id = ?",
                (int(user_id),),
            ).fetchall()
            if rows:
                conn.execute("DELETE FROM faces WHERE user_id = ?", (int(user_id),))
                conn.commit()

        face_ids = [int(row["id"]) for row in rows]
        for face_id in face_ids:
            self._face_meta_cache.pop(face_id, None)
            if self._enable_embedding_cache:
                self._embedding_cache.pop(face_id, None)
                self._vector_index.delete(face_id)

        deleted_images = 0
        if remove_image:
            for row in rows:
                image_path = str(row["image_path"] or "")
                if not image_path or image_path.startswith("embedded://"):
                    continue
                image_file = Path(image_path)
                if not image_file.exists():
                    continue
                try:
                    image_file.unlink(missing_ok=True)
                    deleted_images += 1
                except Exception:
                    continue

        return {
            "user_id": int(user_id),
            "deleted_faces": len(face_ids),
            "deleted_images": deleted_images,
        }

    def verify_user_credentials(
        self,
        *,
        username: str,
        password: str,
        allowed_roles: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        username_text = str(username or "").strip()
        if not username_text:
            return None

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT id, username, password_hash, role, display_name, is_active, create_time
                FROM users
                WHERE username = ?
                LIMIT 1
                """,
                (username_text,),
            ).fetchone()
            if row is None:
                return None
            if int(row["is_active"]) != 1:
                return None
            if allowed_roles and str(row["role"]).lower() not in {x.lower() for x in allowed_roles}:
                return None
            if not _password_verify(password, str(row["password_hash"])):
                return None
            return self._serialize_user_row(row)

    def create_teacher_token(self, *, user_id: int, ttl_seconds: int = 8 * 3600) -> Dict[str, Any]:
        expires_at_ms = _now_ms() + max(60, int(ttl_seconds)) * 1000
        token = secrets.token_urlsafe(32)
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM teacher_tokens WHERE expires_at_ms < ?",
                (_now_ms(),),
            )
            conn.execute(
                """
                INSERT INTO teacher_tokens (user_id, token, expires_at_ms)
                VALUES (?, ?, ?)
                """,
                (int(user_id), token, int(expires_at_ms)),
            )
            conn.commit()
        return {"token": token, "expires_at_ms": int(expires_at_ms)}

    def create_user_token(self, *, user_id: int, ttl_seconds: int = 8 * 3600) -> Dict[str, Any]:
        return self.create_teacher_token(user_id=user_id, ttl_seconds=ttl_seconds)

    def get_user_by_teacher_token(self, token: str) -> Optional[Dict[str, Any]]:
        token_text = str(token or "").strip()
        if not token_text:
            return None

        now_ms = _now_ms()
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT
                    u.id, u.username, u.role, u.display_name, u.is_active, u.create_time,
                    t.id AS token_id, t.expires_at_ms
                FROM teacher_tokens AS t
                JOIN users AS u ON u.id = t.user_id
                WHERE t.token = ?
                LIMIT 1
                """,
                (token_text,),
            ).fetchone()
            if row is None:
                return None
            if int(row["expires_at_ms"]) < now_ms or int(row["is_active"]) != 1:
                conn.execute("DELETE FROM teacher_tokens WHERE token = ?", (token_text,))
                conn.commit()
                return None
            conn.execute(
                "UPDATE teacher_tokens SET last_used_time = CURRENT_TIMESTAMP WHERE id = ?",
                (int(row["token_id"]),),
            )
            conn.commit()
            return self._serialize_user_row(row)

    def get_user_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        return self.get_user_by_teacher_token(token)

    def revoke_teacher_token(self, token: str) -> bool:
        token_text = str(token or "").strip()
        if not token_text:
            return False
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM teacher_tokens WHERE token = ?", (token_text,))
            conn.commit()
            return cursor.rowcount > 0

    def revoke_user_token(self, token: str) -> bool:
        return self.revoke_teacher_token(token)

    def ensure_default_course_for_user(self, *, user_id: int) -> Dict[str, Any]:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT id, course_name, course_code, teacher_user_id, is_active, create_time
                FROM courses
                WHERE teacher_user_id = ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (int(user_id),),
            ).fetchone()
            if row is None:
                cursor = conn.cursor()
                code = f"SCENE{int(user_id):04d}"
                cursor.execute(
                    """
                    INSERT INTO courses (course_name, course_code, teacher_user_id, is_active)
                    VALUES (?, ?, ?, 1)
                    """,
                    ("默认场景", code, int(user_id)),
                )
                conn.commit()
                row = conn.execute(
                    """
                    SELECT id, course_name, course_code, teacher_user_id, is_active, create_time
                    FROM courses
                    WHERE id = ?
                    """,
                    (int(cursor.lastrowid),),
                ).fetchone()
            if row is None:
                raise RuntimeError("初始化默认场景失败")
            return {
                "course_id": int(row["id"]),
                "course_name": str(row["course_name"]),
                "course_code": str(row["course_code"]),
                "teacher_user_id": int(row["teacher_user_id"]),
                "is_active": bool(int(row["is_active"])),
                "create_time": row["create_time"],
            }

    def list_courses_by_teacher(self, *, teacher_user_id: int, include_inactive: bool = False) -> List[Dict[str, Any]]:
        query = """
            SELECT id, course_name, course_code, teacher_user_id, is_active, create_time
            FROM courses
            WHERE teacher_user_id = ?
        """
        params: List[Any] = [int(teacher_user_id)]
        if not include_inactive:
            query += " AND is_active = 1"
        query += " ORDER BY id DESC"
        with self._connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [
            {
                "course_id": int(row["id"]),
                "course_name": str(row["course_name"]),
                "course_code": str(row["course_code"]),
                "teacher_user_id": int(row["teacher_user_id"]),
                "is_active": bool(int(row["is_active"])),
                "create_time": row["create_time"],
            }
            for row in rows
        ]

    def create_course(
        self,
        *,
        teacher_user_id: int,
        course_name: str,
        course_code: str,
    ) -> Dict[str, Any]:
        name_text = str(course_name or "").strip()
        code_text = str(course_code or "").strip().upper()
        if not name_text:
            raise ValueError("course_name 不能为空")
        if not code_text:
            raise ValueError("course_code 不能为空")

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO courses (course_name, course_code, teacher_user_id, is_active)
                VALUES (?, ?, ?, 1)
                """,
                (name_text, code_text, int(teacher_user_id)),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT id, course_name, course_code, teacher_user_id, is_active, create_time
                FROM courses
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
            if row is None:
                raise RuntimeError("创建课程失败")
            return {
                "course_id": int(row["id"]),
                "course_name": str(row["course_name"]),
                "course_code": str(row["course_code"]),
                "teacher_user_id": int(row["teacher_user_id"]),
                "is_active": bool(int(row["is_active"])),
                "create_time": row["create_time"],
            }

    def _serialize_attendance_session_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "session_id": int(row["id"]),
            "course_id": int(row["course_id"]),
            "teacher_user_id": int(row["teacher_user_id"]),
            "title": str(row["title"]),
            "status": str(row["status"]),
            "start_time_ms": int(row["start_time_ms"]),
            "end_time_ms": int(row["end_time_ms"]),
            "geofence_enabled": bool(int(row["geofence_enabled"])),
            "center_lat": row["center_lat"],
            "center_lng": row["center_lng"],
            "radius_m": row["radius_m"],
            "face_threshold": float(row["face_threshold"]),
            "top_k": int(row["top_k"]),
            "strict_liveness_required": bool(int(row["strict_liveness_required"])),
            "strict_liveness_full_actions": bool(int(row["strict_liveness_full_actions"])),
            "checkin_once": bool(int(row["checkin_once"])),
            "qr_token": str(row["qr_token"]),
            "qr_expires_at_ms": int(row["qr_expires_at_ms"]),
            "create_time": row["create_time"],
            "closed_time": row["closed_time"],
            "course_name": row["course_name"] if "course_name" in row.keys() else None,
            "course_code": row["course_code"] if "course_code" in row.keys() else None,
        }

    def create_attendance_session(
        self,
        *,
        course_id: int,
        teacher_user_id: int,
        title: str,
        start_time_ms: int,
        end_time_ms: int,
        geofence_enabled: bool,
        center_lat: Optional[float],
        center_lng: Optional[float],
        radius_m: Optional[float],
        face_threshold: float,
        top_k: int,
        strict_liveness_required: bool,
        checkin_once: bool,
        strict_liveness_full_actions: bool = False,
        qr_ttl_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        title_text = str(title or "").strip() or "课堂签到"
        start_ms = int(start_time_ms)
        end_ms = int(end_time_ms)
        if end_ms <= start_ms:
            raise ValueError("end_time_ms 必须晚于 start_time_ms")
        qr_expires_at_ms = int(start_ms + (qr_ttl_ms if qr_ttl_ms is not None else (end_ms - start_ms)))
        qr_expires_at_ms = max(qr_expires_at_ms, end_ms)
        token = secrets.token_urlsafe(24)

        with self._connection() as conn:
            course_row = conn.execute(
                """
                SELECT id
                FROM courses
                WHERE id = ? AND teacher_user_id = ? AND is_active = 1
                LIMIT 1
                """,
                (int(course_id), int(teacher_user_id)),
            ).fetchone()
            if course_row is None:
                raise ValueError("课程不存在或不属于当前教师")

            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO attendance_sessions (
                    course_id, teacher_user_id, title, status,
                    start_time_ms, end_time_ms,
                    geofence_enabled, center_lat, center_lng, radius_m,
                    face_threshold, top_k, strict_liveness_required, strict_liveness_full_actions, checkin_once,
                    qr_token, qr_expires_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(course_id),
                    int(teacher_user_id),
                    title_text,
                    "active",
                    start_ms,
                    end_ms,
                    1 if geofence_enabled else 0,
                    center_lat,
                    center_lng,
                    radius_m,
                    float(face_threshold),
                    int(top_k),
                    1 if strict_liveness_required else 0,
                    1 if strict_liveness_full_actions else 0,
                    1 if checkin_once else 0,
                    token,
                    qr_expires_at_ms,
                ),
            )
            session_id = int(cursor.lastrowid)
            conn.commit()
            return self.get_attendance_session_by_id(session_id=session_id, teacher_user_id=teacher_user_id) or {}

    def get_attendance_session_by_id(
        self,
        *,
        session_id: int,
        teacher_user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        query = """
            SELECT
                s.*,
                c.course_name,
                c.course_code
            FROM attendance_sessions AS s
            JOIN courses AS c ON c.id = s.course_id
            WHERE s.id = ?
        """
        params: List[Any] = [int(session_id)]
        if teacher_user_id is not None:
            query += " AND s.teacher_user_id = ?"
            params.append(int(teacher_user_id))
        query += " LIMIT 1"
        with self._connection() as conn:
            row = conn.execute(query, tuple(params)).fetchone()
        if row is None:
            return None
        return self._serialize_attendance_session_row(row)

    def get_attendance_session_by_qr_token(self, *, token: str) -> Optional[Dict[str, Any]]:
        token_text = str(token or "").strip()
        if not token_text:
            return None
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT
                    s.*,
                    c.course_name,
                    c.course_code
                FROM attendance_sessions AS s
                JOIN courses AS c ON c.id = s.course_id
                WHERE s.qr_token = ?
                LIMIT 1
                """,
                (token_text,),
            ).fetchone()
        if row is None:
            return None
        return self._serialize_attendance_session_row(row)

    def list_attendance_sessions(
        self,
        *,
        teacher_user_id: int,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT
                s.*,
                c.course_name,
                c.course_code
            FROM attendance_sessions AS s
            JOIN courses AS c ON c.id = s.course_id
            WHERE s.teacher_user_id = ?
        """
        params: List[Any] = [int(teacher_user_id)]
        if status:
            query += " AND s.status = ?"
            params.append(str(status).strip())
        query += " ORDER BY s.id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._serialize_attendance_session_row(row) for row in rows]

    def close_attendance_session(self, *, session_id: int, teacher_user_id: int) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE attendance_sessions
                SET status = 'closed', closed_time = CURRENT_TIMESTAMP
                WHERE id = ? AND teacher_user_id = ?
                """,
                (int(session_id), int(teacher_user_id)),
            )
            conn.commit()
            if cursor.rowcount <= 0:
                return None
        return self.get_attendance_session_by_id(session_id=session_id, teacher_user_id=teacher_user_id)

    def has_attendance_success_record(
        self,
        *,
        session_id: int,
        person_name: Optional[str] = None,
        matched_user_id: Optional[int] = None,
    ) -> bool:
        if matched_user_id is None:
            name_text = str(person_name or "").strip()
            if not name_text:
                return False
            query = """
                SELECT id
                FROM attendance_records
                WHERE session_id = ? AND person_name = ? AND status = 'success'
                ORDER BY id DESC
                LIMIT 1
            """
            params: Tuple[Any, ...] = (int(session_id), name_text)
        else:
            query = """
                SELECT id
                FROM attendance_records
                WHERE session_id = ? AND matched_user_id = ? AND status = 'success'
                ORDER BY id DESC
                LIMIT 1
            """
            params = (int(session_id), int(matched_user_id))
        with self._connection() as conn:
            row = conn.execute(query, params).fetchone()
        return row is not None

    def add_attendance_record(
        self,
        *,
        session_id: int,
        status: str,
        reason: Optional[str] = None,
        person_name: Optional[str] = None,
        matched_face_id: Optional[int] = None,
        matched_user_id: Optional[int] = None,
        similarity: Optional[float] = None,
        capture_image_path: Optional[Union[str, Path]] = None,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        distance_m: Optional[float] = None,
    ) -> int:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO attendance_records (
                    session_id, person_name, matched_face_id, matched_user_id, similarity,
                    status, reason, capture_image_path, lat, lng, distance_m
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(session_id),
                    person_name,
                    matched_face_id,
                    int(matched_user_id) if matched_user_id is not None else None,
                    similarity,
                    str(status or "").strip() or "unknown",
                    reason,
                    str(Path(capture_image_path).resolve()) if capture_image_path else None,
                    lat,
                    lng,
                    distance_m,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_attendance_records(self, *, session_id: int, limit: int = 500) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    id, session_id, person_name, matched_face_id, matched_user_id, similarity,
                    status, reason, capture_image_path, lat, lng, distance_m, create_time
                FROM attendance_records
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(session_id), max(1, int(limit))),
            ).fetchall()
        return [
            {
                "record_id": int(row["id"]),
                "session_id": int(row["session_id"]),
                "person_name": row["person_name"],
                "matched_face_id": row["matched_face_id"],
                "matched_user_id": row["matched_user_id"],
                "similarity": row["similarity"],
                "status": row["status"],
                "reason": row["reason"],
                "capture_image_path": row["capture_image_path"],
                "lat": row["lat"],
                "lng": row["lng"],
                "distance_m": row["distance_m"],
                "create_time": row["create_time"],
            }
            for row in rows
        ]

    def summarize_attendance_records(self, *, session_id: int) -> Dict[str, Any]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS cnt
                FROM attendance_records
                WHERE session_id = ?
                GROUP BY status
                """,
                (int(session_id),),
            ).fetchall()
            unique_success = conn.execute(
                """
                SELECT COUNT(DISTINCT COALESCE(CAST(matched_user_id AS TEXT), person_name)) AS cnt
                FROM attendance_records
                WHERE session_id = ?
                  AND status = 'success'
                  AND COALESCE(CAST(matched_user_id AS TEXT), person_name) IS NOT NULL
                  AND COALESCE(CAST(matched_user_id AS TEXT), person_name) != ''
                """,
                (int(session_id),),
            ).fetchone()

        status_counts = {str(row["status"]): int(row["cnt"]) for row in rows}
        return {
            "session_id": int(session_id),
            "total_records": int(sum(status_counts.values())),
            "status_counts": status_counts,
            "unique_success_count": int(unique_success["cnt"]) if unique_success else 0,
        }

    def close(self) -> None:
        self._query_embedding_cache.clear()
        self._embedding_cache.clear()
        self._face_meta_cache.clear()
        self._vector_index.clear()
        if self._memory_conn is not None:
            self._memory_conn.close()
            self._memory_conn = None
