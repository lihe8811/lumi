import unittest

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.dependencies import get_db_client
from backend.db import InMemoryDbClient


class BackendApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        db = get_db_client()
        if isinstance(db, InMemoryDbClient):
            db.reset()

    def test_request_import_and_status(self):
        response = self.client.post(
            "/api/request_arxiv_doc_import",
            json={"arxiv_id": "1234.56789", "version": "1"},
        )
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["arxiv_id"], "1234.56789")
        self.assertEqual(payload["status"], "WAITING")

        status_resp = self.client.get(f"/api/job-status/{payload['job_id']}")
        self.assertEqual(status_resp.status_code, 200)
        status_payload = status_resp.json()
        self.assertEqual(status_payload["job_id"], payload["job_id"])
        self.assertEqual(status_payload["status"], "WAITING")

    def test_sign_url_uses_storage_client(self):
        response = self.client.get("/api/sign-url", params={"path": "foo/bar.png"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("url", response.json())
        self.assertIn("foo/bar.png", response.json()["url"])

    def test_save_user_feedback(self):
        response = self.client.post(
            "/api/save_user_feedback",
            json={"arxiv_id": "1234.56789", "user_feedback_text": "nice!"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

        db = get_db_client()
        if isinstance(db, InMemoryDbClient):
            self.assertEqual(len(db.feedback), 1)


if __name__ == "__main__":
    unittest.main()
