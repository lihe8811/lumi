import unittest

from backend.db import FeedbackRecord, PostgresDbClient
from shared.types import LoadingStatus


class PostgresDbClientTests(unittest.TestCase):
    """
    Uses SQLite via SQLAlchemy URL for fast/local testing of the Postgres client logic.
    """

    @classmethod
    def setUpClass(cls):
        cls.db = PostgresDbClient("sqlite+pysqlite:///:memory:")

    def test_create_and_get_job(self):
        job = self.db.create_import_job("1234.56789", "1")
        self.assertEqual(job.status, LoadingStatus.WAITING)
        fetched = self.db.get_job(job.job_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.job_id, job.job_id)

    def test_metadata_roundtrip(self):
        self.db.save_metadata("arxiv:1", {"foo": "bar"})
        meta = self.db.get_metadata("arxiv:1")
        self.assertEqual(meta, {"foo": "bar"})

    def test_save_feedback(self):
        record = FeedbackRecord(
            arxiv_id="arxiv:1",
            version="1",
            user_feedback_text="nice",
        )
        self.db.save_feedback(record)

    def test_fetch_next_waiting_job_and_update(self):
        job = self.db.create_import_job("abc", "1")
        fetched = self.db.fetch_next_waiting_job()
        self.assertIsNotNone(fetched)
        # Depending on DB state, first waiting job may differ; ensure it exists.

        self.db.update_job_progress(
            job.job_id,
            status=LoadingStatus.SUCCESS,
            stage="DONE",
            progress_percent=1.0,
        )
        updated = self.db.get_job(job.job_id)
        self.assertEqual(updated.status, LoadingStatus.SUCCESS)
        self.assertEqual(updated.stage, "DONE")
        self.assertEqual(updated.progress_percent, 1.0)

    def test_save_and_get_lumi_doc(self):
        doc = {"foo": "bar"}
        summaries = {"s": 1}
        self.db.save_lumi_doc("paper", "1", doc, summaries)
        loaded = self.db.get_lumi_doc("paper", "1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded[0], doc)
        self.assertEqual(loaded[1], summaries)


if __name__ == "__main__":
    unittest.main()
