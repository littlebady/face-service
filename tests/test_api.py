import importlib
import hashlib
import json
import shutil
import time
import unittest
import uuid
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient

import db_manager


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


EMBEDDING = np.ones(512, dtype=np.float32)
TEST_TMP_ROOT = Path(__file__).resolve().parents[1] / ".tmp_tests"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)

db_manager.get_face_app = lambda det_size=(640, 640): FakeApp(EMBEDDING)
api = importlib.import_module("api")


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.root = TEST_TMP_ROOT / f"api_{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.media_root = self.root / "media"
        self.db_path = self.root / "unused.db"

        self.face_db = db_manager.FaceDB(db_path=":memory:", face_app=FakeApp(EMBEDDING))
        app = api.create_test_app(
            db_path=self.db_path,
            media_root=self.media_root,
            admin_token="test-admin-token",
            face_db=self.face_db,
        )
        self.client = TestClient(app)
        self.admin_headers = {"Authorization": "Bearer test-admin-token"}

    def tearDown(self):
        self.face_db.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def make_image_bytes(self):
        image = np.full((96, 96, 3), 180, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", image)
        self.assertTrue(ok)
        return encoded.tobytes()

    def test_register_persists_image(self):
        response = self.client.post(
            "/faces/register",
            data={"name": "张三"},
            files={"file": ("face.jpg", self.make_image_bytes(), "image/jpeg")},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        stored_path = Path(payload["face"]["image_path"])
        self.assertTrue(stored_path.exists())

        faces_response = self.client.get("/faces?limit=5")
        self.assertEqual(faces_response.status_code, 200)
        faces = faces_response.json()["faces"]
        self.assertEqual(len(faces), 1)
        self.assertEqual(faces[0]["person_name"], "张三")
        self.assertIn("face_detect", payload)
        self.assertEqual(payload["face_detect"]["face_count"], 1)
        self.assertFalse(payload["face_detect"]["multiple_faces"])

    def test_checkin_creates_history_record(self):
        image_bytes = self.make_image_bytes()
        self.client.post(
            "/faces/register",
            data={"name": "李四"},
            files={"file": ("face.jpg", image_bytes, "image/jpeg")},
        )

        response = self.client.post(
            "/checkin",
            data={"lat": "30.123", "lng": "120.456", "threshold": "0.6"},
            files={"file": ("checkin.jpg", image_bytes, "image/jpeg")},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "success")
        self.assertTrue(payload["capture_image_url"].startswith("/media/"))

        history_response = self.client.get("/checkins?limit=5")
        self.assertEqual(history_response.status_code, 200)
        records = history_response.json()["records"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "success")
        self.assertEqual(records[0]["person_name"], "李四")

    def test_strict_liveness_requires_ticket_and_session_binding(self):
        strict_root = self.root / "strict"
        strict_root.mkdir(parents=True, exist_ok=True)
        strict_media_root = strict_root / "media"
        strict_db = db_manager.FaceDB(db_path=":memory:", face_app=FakeApp(EMBEDDING))
        strict_client = None
        try:
            strict_app = api.create_test_app(
                db_path=strict_root / "unused.db",
                media_root=strict_media_root,
                admin_token="test-admin-token",
                face_db=strict_db,
                strict_liveness_required=True,
                antispoof_required=False,
            )
            strict_client = TestClient(strict_app)

            image_bytes = self.make_image_bytes()
            strict_client.post(
                "/faces/register",
                data={"name": "严格用户"},
                files={"file": ("face.jpg", image_bytes, "image/jpeg")},
            )

            no_proof_resp = strict_client.post(
                "/checkin",
                data={"lat": "30.123", "lng": "120.456", "threshold": "0.6"},
                files={"file": ("checkin.jpg", image_bytes, "image/jpeg")},
            )
            self.assertEqual(no_proof_resp.status_code, 200)
            no_proof_payload = no_proof_resp.json()
            self.assertFalse(no_proof_payload["ok"])
            self.assertEqual(no_proof_payload["status"], "liveness_failed")

            challenge_resp = strict_client.post("/checkins/liveness/challenge")
            self.assertEqual(challenge_resp.status_code, 200)
            challenge_payload = challenge_resp.json()
            self.assertTrue(challenge_payload["ok"])
            self.assertTrue(challenge_payload["challenge_id"])
            self.assertTrue(challenge_payload["nonce"])
            self.assertTrue(challenge_payload["actions"])

            now_ms = int(time.time() * 1000)
            duration_ms = 6500
            proof = {
                "mode": "strict",
                "challenge_id": challenge_payload["challenge_id"],
                "nonce": challenge_payload["nonce"],
                "actions": challenge_payload["actions"],
                "started_at_ms": now_ms - duration_ms,
                "passed_at_ms": now_ms,
                "duration_ms": duration_ms,
                "metrics": {
                    "motion_score": 0.003,
                    "missing_frames": 0,
                    "max_freeze_run": 4,
                    "blink_count": 1,
                    "yaw_span": 0.22,
                    "mouth_peak_gain": 0.02,
                    "scale_peak_gain": 0.01,
                },
            }

            missing_ticket_resp = strict_client.post(
                "/checkin",
                data={
                    "lat": "30.123",
                    "lng": "120.456",
                    "threshold": "0.6",
                    "liveness_proof": json.dumps(proof),
                },
                files={"file": ("checkin.jpg", image_bytes, "image/jpeg")},
            )
            self.assertEqual(missing_ticket_resp.status_code, 200)
            self.assertFalse(missing_ticket_resp.json()["ok"])
            self.assertEqual(missing_ticket_resp.json()["status"], "liveness_failed")

            verify_resp = strict_client.post(
                "/checkins/liveness/verify",
                data={
                    "proof": json.dumps(proof),
                    "key_image_hash": hashlib.sha256(image_bytes).hexdigest(),
                },
                files=[
                    ("key_image", ("key.jpg", image_bytes, "image/jpeg")),
                    ("evidence_frames", ("ev1.jpg", image_bytes, "image/jpeg")),
                    ("evidence_frames", ("ev2.jpg", image_bytes, "image/jpeg")),
                ],
            )
            self.assertEqual(verify_resp.status_code, 200)
            verify_payload = verify_resp.json()
            self.assertTrue(verify_payload["ok"])
            self.assertTrue(verify_payload["liveness_ticket"])

            ticket = verify_payload["liveness_ticket"]
            with_ticket_resp = strict_client.post(
                "/checkin",
                data={
                    "lat": "30.123",
                    "lng": "120.456",
                    "threshold": "0.6",
                    "liveness_ticket": ticket,
                },
                files={"file": ("checkin.jpg", image_bytes, "image/jpeg")},
            )
            self.assertEqual(with_ticket_resp.status_code, 200)
            with_ticket_payload = with_ticket_resp.json()
            self.assertTrue(with_ticket_payload["ok"])
            self.assertEqual(with_ticket_payload["status"], "success")

            replay_resp = strict_client.post(
                "/checkin",
                data={
                    "lat": "30.123",
                    "lng": "120.456",
                    "threshold": "0.6",
                    "liveness_ticket": ticket,
                },
                files={"file": ("checkin.jpg", image_bytes, "image/jpeg")},
            )
            self.assertEqual(replay_resp.status_code, 200)
            self.assertFalse(replay_resp.json()["ok"])
            self.assertEqual(replay_resp.json()["status"], "liveness_failed")
        finally:
            if strict_client is not None:
                strict_client.close()
            strict_db.close()

    def test_admin_apis_and_geofence_suggestion(self):
        image_bytes = self.make_image_bytes()
        register_response = self.client.post(
            "/faces/register",
            data={"name": "王五"},
            files={"file": ("face.jpg", image_bytes, "image/jpeg")},
        )
        self.assertEqual(register_response.status_code, 200)
        face_id = register_response.json()["face_id"]

        checkin_points = [
            ("30.1230", "120.4560"),
            ("30.1232", "120.4561"),
            ("30.1229", "120.4559"),
        ]
        for lat, lng in checkin_points:
            response = self.client.post(
                "/checkin",
                data={"lat": lat, "lng": lng, "threshold": "0.6"},
                files={"file": ("checkin.jpg", image_bytes, "image/jpeg")},
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["ok"])

        suggestion_response = self.client.get("/checkins/geofence/suggest?person_name=王五")
        self.assertEqual(suggestion_response.status_code, 200)
        suggestion = suggestion_response.json()
        self.assertTrue(suggestion["ok"])
        self.assertGreaterEqual(suggestion["cluster_size"], 3)

        person_records_response = self.client.get(
            "/admin/checkins/person/王五?limit=10",
            headers=self.admin_headers,
        )
        self.assertEqual(person_records_response.status_code, 200)
        person_records = person_records_response.json()["records"]
        self.assertGreaterEqual(len(person_records), 3)

        export_response = self.client.get(
            "/admin/checkins/export?person_name=王五&limit=20",
            headers=self.admin_headers,
        )
        self.assertEqual(export_response.status_code, 200)
        self.assertIn("text/csv", export_response.headers.get("content-type", ""))
        self.assertIn("checkin_id", export_response.text)
        self.assertIn("王五", export_response.text)

        delete_response = self.client.delete(f"/admin/faces/{face_id}", headers=self.admin_headers)
        self.assertEqual(delete_response.status_code, 200)
        self.assertTrue(delete_response.json()["ok"])

        batch_response = self.client.post(
            "/admin/faces/batch-embeddings",
            headers=self.admin_headers,
            json={
                "records": [
                    {
                        "person_name": "批量用户",
                        "embedding": EMBEDDING.tolist(),
                        "image_path": "embedded://batch_user",
                    }
                ]
            },
        )
        self.assertEqual(batch_response.status_code, 200)
        self.assertTrue(batch_response.json()["ok"])
        self.assertEqual(batch_response.json()["result"]["inserted"], 1)

        stats_response = self.client.get("/admin/vector-index/stats", headers=self.admin_headers)
        self.assertEqual(stats_response.status_code, 200)
        stats_payload = stats_response.json()
        self.assertTrue(stats_payload["ok"])
        self.assertIn("backend", stats_payload["stats"])
        self.assertIn("size", stats_payload["stats"])

    def test_profile_update_and_profile_face_registration(self):
        register_resp = self.client.post(
            "/auth/register",
            json={
                "username": "profile_user",
                "password": "profile123",
                "display_name": "初始昵称",
            },
        )
        self.assertEqual(register_resp.status_code, 200)
        token = register_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        profile_resp = self.client.get("/auth/profile", headers=headers)
        self.assertEqual(profile_resp.status_code, 200)
        profile_payload = profile_resp.json()["profile"]
        self.assertFalse(profile_payload["has_face"])
        self.assertEqual(profile_payload["face_count"], 0)

        update_resp = self.client.put(
            "/auth/profile",
            headers=headers,
            json={"display_name": "新昵称"},
        )
        self.assertEqual(update_resp.status_code, 200)
        self.assertEqual(update_resp.json()["user"]["display_name"], "新昵称")

        image_bytes = self.make_image_bytes()
        first_face_resp = self.client.post(
            "/auth/profile/face/register",
            headers=headers,
            files={"file": ("profile.jpg", image_bytes, "image/jpeg")},
        )
        self.assertEqual(first_face_resp.status_code, 200)
        self.assertTrue(first_face_resp.json()["ok"])
        self.assertEqual(first_face_resp.json()["face_count"], 1)

        second_face_resp = self.client.post(
            "/auth/profile/face/register",
            headers=headers,
            files={"file": ("profile2.jpg", image_bytes, "image/jpeg")},
        )
        self.assertEqual(second_face_resp.status_code, 200)
        self.assertTrue(second_face_resp.json()["ok"])
        self.assertEqual(second_face_resp.json()["face_count"], 1)
        self.assertGreaterEqual(second_face_resp.json()["replaced_faces"], 1)

        profile_resp2 = self.client.get("/auth/profile", headers=headers)
        self.assertEqual(profile_resp2.status_code, 200)
        profile_payload2 = profile_resp2.json()["profile"]
        self.assertTrue(profile_payload2["has_face"])
        self.assertEqual(profile_payload2["face_count"], 1)
        self.assertEqual(profile_payload2["display_name"], "新昵称")
        self.assertEqual(profile_payload2["latest_face"]["user_id"], profile_payload2["user_id"])

    def test_admin_requires_token(self):
        response = self.client.get("/admin/checkins/export")
        self.assertEqual(response.status_code, 401)

    def test_multi_face_selects_largest(self):
        image_bytes = self.make_image_bytes()
        large = np.ones(512, dtype=np.float32)
        small = np.full(512, 0.5, dtype=np.float32)
        self.face_db.app = MultiFaceApp(
            embeddings=[small, large],
            bboxes=[
                [10, 10, 30, 30],   # small area
                [5, 5, 90, 90],     # large area
            ],
        )

        response = self.client.post(
            "/faces/register",
            data={"name": "多人脸用户"},
            files={"file": ("face.jpg", image_bytes, "image/jpeg")},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["face_detect"]["multiple_faces"])
        self.assertEqual(payload["face_detect"]["selected_face_index"], 1)
        self.assertIsNotNone(payload["face_detect"]["warning"])


if __name__ == "__main__":
    unittest.main()
