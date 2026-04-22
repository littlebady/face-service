import shutil
import unittest
import uuid
from pathlib import Path

import cv2
import numpy as np

from db_manager import FaceDB


class FakeFace:
    def __init__(self, embedding, bbox=None):
        self.embedding = embedding
        if bbox is not None:
            self.bbox = np.asarray(bbox, dtype=np.float32)


class FakeApp:
    def __init__(self, embedding):
        self.embedding = embedding

    def get(self, image):
        return [FakeFace(self.embedding)]


class MultiFaceApp:
    def __init__(self, embeddings, bboxes):
        self.embeddings = embeddings
        self.bboxes = bboxes

    def get(self, image):
        return [FakeFace(emb, bbox=bbox) for emb, bbox in zip(self.embeddings, self.bboxes)]


TEST_TMP_ROOT = Path(__file__).resolve().parents[1] / ".tmp_tests"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)


class FaceDBTestCase(unittest.TestCase):
    def setUp(self):
        self.root = TEST_TMP_ROOT / f"db_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.image_path = self.root / "face.jpg"

        image = np.full((80, 80, 3), 255, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", image)
        self.assertTrue(ok)
        self.image_path.write_bytes(encoded.tobytes())
        self.embedding = np.ones(512, dtype=np.float32)
        self.db = FaceDB(db_path=":memory:", face_app=FakeApp(self.embedding))

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_add_face_and_search(self):
        face_id = self.db.add_face("测试用户", self.image_path)
        self.assertEqual(face_id, 1)

        faces = self.db.get_all_faces(limit=5)
        self.assertEqual(len(faces), 1)
        self.assertEqual(Path(faces[0]["image_path"]), self.image_path.resolve())

        results = self.db.search_face(embedding=self.embedding, threshold=0.1, top_k=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["person_name"], "测试用户")
        self.assertGreaterEqual(results[0]["similarity"], 0.99)

    def test_add_checkin_record_and_query(self):
        self.db.add_face("测试用户", self.image_path)
        checkin_id = self.db.add_checkin_record(
            capture_image_path=self.image_path,
            status="success",
            reason="签到成功",
            person_name="测试用户",
            matched_face_id=1,
            similarity=0.99,
            matched_image_path=self.image_path,
            lat=30.1,
            lng=120.2,
            center_lat=30.1,
            center_lng=120.2,
            radius_m=100.0,
            distance_m=0.0,
        )

        self.assertEqual(checkin_id, 1)
        records = self.db.get_recent_checkins(limit=5)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "success")
        self.assertEqual(records[0]["person_name"], "测试用户")

    def test_geofence_suggestion_and_delete_face(self):
        face_id = self.db.add_face("聚类用户", self.image_path)
        points = [
            (30.1000, 120.2000),
            (30.1002, 120.2001),
            (30.0998, 120.1999),
            (30.1001, 120.2002),
        ]
        for lat, lng in points:
            self.db.add_checkin_record(
                capture_image_path=self.image_path,
                status="success",
                person_name="聚类用户",
                lat=lat,
                lng=lng,
            )

        suggestion = self.db.suggest_geofence_from_history(person_name="聚类用户", min_samples=3)
        self.assertTrue(suggestion["ok"])
        self.assertGreaterEqual(suggestion["cluster_size"], 3)
        self.assertIn("center_lat", suggestion)
        self.assertIn("center_lng", suggestion)

        delete_result = self.db.delete_face(face_id=face_id, remove_image=False)
        self.assertEqual(delete_result["face_id"], face_id)
        with self.assertRaises(ValueError):
            self.db.delete_face(face_id=face_id, remove_image=False)

    def test_batch_embeddings_and_index_stats(self):
        rng = np.random.default_rng(42)
        records = []
        for i in range(12):
            embedding = rng.normal(size=512).astype(np.float32)
            records.append(
                {
                    "person_name": f"user_{i}",
                    "embedding": embedding,
                    "image_path": f"embedded://user_{i}",
                }
            )

        batch_result = self.db.add_face_embeddings_batch(records)
        self.assertTrue(batch_result["ok"])
        self.assertEqual(batch_result["inserted"], 12)
        self.assertEqual(len(batch_result["face_ids"]), 12)

        stats = self.db.get_vector_index_stats()
        self.assertEqual(stats["size"], 12)
        self.assertTrue(stats["embedding_cache_enabled"])

        query = np.asarray(records[3]["embedding"], dtype=np.float32)
        result = self.db.search_face(embedding=query, threshold=0.2, top_k=1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["person_name"], "user_3")

        db_scan = FaceDB(
            db_path=":memory:",
            face_app=FakeApp(self.embedding),
            enable_embedding_cache=False,
            vector_backend="bruteforce",
        )
        try:
            scan_batch = db_scan.add_face_embeddings_batch(records)
            self.assertEqual(scan_batch["inserted"], 12)
            scan_result = db_scan.search_face(embedding=query, threshold=0.2, top_k=1)
            self.assertEqual(len(scan_result), 1)
            self.assertEqual(scan_result[0]["person_name"], "user_3")
        finally:
            db_scan.close()

    def test_largest_face_selection_analysis(self):
        emb_small = np.full(512, 0.1, dtype=np.float32)
        emb_large = np.full(512, 0.9, dtype=np.float32)
        db = FaceDB(
            db_path=":memory:",
            face_app=MultiFaceApp(
                embeddings=[emb_small, emb_large],
                bboxes=[[0, 0, 20, 20], [0, 0, 80, 80]],
            ),
        )
        try:
            add_result = db.add_face_with_analysis("多人脸", self.image_path)
            self.assertEqual(add_result["face_detect"]["face_count"], 2)
            self.assertTrue(add_result["face_detect"]["multiple_faces"])
            self.assertEqual(add_result["face_detect"]["selected_face_index"], 1)

            search_result = db.search_face_with_analysis(image_path=self.image_path, top_k=1, threshold=0.0)
            self.assertEqual(search_result["face_detect"]["selected_face_index"], 1)
            self.assertEqual(len(search_result["results"]), 1)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
