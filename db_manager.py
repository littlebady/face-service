from __future__ import annotations

from collections import OrderedDict
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import math
import sqlite3

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
                "SELECT id, person_name, embedding, image_path, create_time FROM faces"
            ).fetchall()
        return rows

    def _reload_face_cache_and_index(self) -> None:
        rows = self._load_faces_for_search()

        self._face_meta_cache = {
            int(row["id"]): {
                "face_id": int(row["id"]),
                "person_name": str(row["person_name"]),
                "image_path": row["image_path"],
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

    def add_face(self, person_name: str, image_path: Union[str, Path]) -> int:
        resolved_path = Path(image_path).resolve()
        embedding = self._extract_embedding_from_image(resolved_path)
        return self.add_face_embedding(
            person_name=person_name,
            embedding=embedding,
            image_path=resolved_path,
        )

    def add_face_with_analysis(self, person_name: str, image_path: Union[str, Path]) -> Dict[str, Any]:
        resolved_path = Path(image_path).resolve()
        analyzed = self._analyze_image_face(resolved_path)
        face_id = self.add_face_embedding(
            person_name=person_name,
            embedding=np.asarray(analyzed["embedding"], dtype=np.float32),
            image_path=resolved_path,
        )
        return {"face_id": face_id, "face_detect": dict(analyzed["face_detect"])}

    def add_face_embedding(
        self,
        *,
        person_name: str,
        embedding: np.ndarray,
        image_path: Union[str, Path],
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
                "INSERT INTO faces (person_name, embedding, image_path) VALUES (?, ?, ?)",
                (person_name.strip(), embedding_np.tobytes(), store_path),
            )
            conn.commit()
            face_id = int(cursor.lastrowid)

        meta = {
            "face_id": face_id,
            "person_name": person_name.strip(),
            "image_path": store_path,
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

        prepared: List[Tuple[str, np.ndarray, str]] = []
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
            prepared.append((person_name, embedding_np, self._normalize_store_path(image_path)))

        face_ids: List[int] = []
        with self._connection() as conn:
            cursor = conn.cursor()
            for person_name, embedding_np, image_path in prepared:
                cursor.execute(
                    "INSERT INTO faces (person_name, embedding, image_path) VALUES (?, ?, ?)",
                    (person_name, embedding_np.tobytes(), image_path),
                )
                face_ids.append(int(cursor.lastrowid))
            conn.commit()

        for face_id, (person_name, embedding_np, image_path) in zip(face_ids, prepared):
            self._face_meta_cache[face_id] = {
                "face_id": face_id,
                "person_name": person_name,
                "image_path": image_path,
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
                "SELECT id, person_name, embedding, image_path, create_time FROM faces"
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
        query = "SELECT id, person_name, image_path, create_time FROM faces ORDER BY id DESC LIMIT ?"
        with self._connection() as conn:
            rows = conn.execute(query, (limit,)).fetchall()

        return [
            {
                "face_id": int(row["id"]),
                "person_name": row["person_name"],
                "image_path": row["image_path"],
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
                "SELECT id, person_name, image_path FROM faces WHERE id = ?",
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

    def close(self) -> None:
        self._query_embedding_cache.clear()
        self._embedding_cache.clear()
        self._face_meta_cache.clear()
        self._vector_index.clear()
        if self._memory_conn is not None:
            self._memory_conn.close()
            self._memory_conn = None
