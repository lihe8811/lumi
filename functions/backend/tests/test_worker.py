import unittest
from unittest.mock import patch

from backend.db import InMemoryDbClient
from backend.queue import InMemoryJobQueue
from backend.worker import process_next
from shared.types import LoadingStatus


class WorkerTests(unittest.TestCase):
    @patch("backend.worker.get_settings")
    def test_process_once_advances_status(self, mock_settings):
        mock_settings.return_value = type(
            "Settings", (), {"use_in_memory_backends": True, "gemini_api_key": None}
        )()
        db = InMemoryDbClient()
        queue = InMemoryJobQueue()
        job = db.create_import_job("1234.56789", "1")
        self.assertEqual(job.status, LoadingStatus.WAITING)

        queue.enqueue(job.job_id)
        processed = process_next(db=db, queue=queue, block=False)
        self.assertTrue(processed)

        updated = db.get_job(job.job_id)
        self.assertEqual(updated.status, LoadingStatus.SUCCESS)
        self.assertIn(updated.stage, ["SUCCESS", "WAITING"])
        self.assertGreaterEqual(updated.progress_percent, 0.0)

    def test_process_once_no_jobs(self):
        db = InMemoryDbClient()
        queue = InMemoryJobQueue()
        processed = process_next(db=db, queue=queue, block=False)
        self.assertFalse(processed)


if __name__ == "__main__":
    unittest.main()
