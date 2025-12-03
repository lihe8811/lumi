"""
Lightweight worker loop to process queued import jobs.

This is a placeholder/stub: it advances WAITING jobs to SUCCESS immediately.
Integrate the real import/summarization pipeline here in future steps.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Optional

from backend.db import DbClient, JobRecord
from backend.dependencies import get_db_client, get_queue_client, get_storage_client
from backend.config import get_settings
from import_pipeline import fetch_utils, import_pipeline, summaries
from models import extract_concepts as extract_concepts_util
from models import api_config
from backend.queue import JobQueue
from shared.types import LoadingStatus
from shared.json_utils import convert_keys
import logging
import os

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def process_job(job: JobRecord, db: DbClient) -> None:
    """
    Process a single job.

    In-memory mode (or missing DB/storage config): stub to SUCCESS.
    Otherwise, runs the import pipeline and marks status accordingly.
    """
    settings = get_settings()

    # Ensure Gemini API key is wired for downstream calls.
    if settings.gemini_api_key:
        api_config.DEFAULT_API_KEY = settings.gemini_api_key
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
        os.environ["GOOGLE_API_KEY"] = settings.gemini_api_key

    # In-memory/dev path: no external calls.
    if settings.use_in_memory_backends:
        db.update_job_status(job.job_id, LoadingStatus.SUCCESS)
        return

    db.update_job_progress(
        job.job_id, status=LoadingStatus.SUMMARIZING, stage="FETCH_METADATA", progress_percent=0.05
    )
    try:
        # License + metadata
        fetch_utils.check_arxiv_license(job.arxiv_id)
        metadata_list = fetch_utils.fetch_arxiv_metadata([job.arxiv_id])
        if len(metadata_list) != 1:
            raise ValueError("Invalid metadata response from arXiv")
        metadata = metadata_list[0]
        db.save_metadata(job.arxiv_id, asdict(metadata))

        # Concepts + import pipeline
        db.update_job_progress(
            job.job_id,
            status=LoadingStatus.SUMMARIZING,
            stage="EXTRACT_CONCEPTS",
            progress_percent=0.15,
        )
        logger.info(f"[{job.job_id}] Extracting concepts via Gemini")
        concepts = extract_concepts_util.extract_concepts(metadata.summary)
        logger.info(f"[{job.job_id}] Concepts extracted: {len(concepts) if concepts else 0}")

        db.update_job_progress(
            job.job_id,
            status=LoadingStatus.SUMMARIZING,
            stage="IMPORT_PIPELINE",
            progress_percent=0.25,
        )
        logger.info(f"[{job.job_id}] Starting import pipeline")
        lumi_doc, _ = import_pipeline.import_arxiv_latex_and_pdf(
            arxiv_id=job.arxiv_id,
            version=metadata.version,
            concepts=concepts or [],
            metadata=metadata,
            run_locally=False,
        )
        logger.info(f"[{job.job_id}] Import pipeline complete")

        db.update_job_progress(
            job.job_id,
            status=LoadingStatus.SUMMARIZING,
            stage="IMPORT_PIPELINE",
            progress_percent=0.5,
        )

        # Summaries (may call LLM)
        total_sections = len(lumi_doc.sections) if lumi_doc and lumi_doc.sections else 1
        db.update_job_progress(
            job.job_id,
            status=LoadingStatus.SUMMARIZING,
            stage="SUMMARIZING",
            progress_percent=0.7,
        )
        logger.info(f"[{job.job_id}] Summarizing {total_sections} sections via LLM")
        lumi_doc.summaries = summaries.generate_lumi_summaries(lumi_doc)
        logger.info(f"[{job.job_id}] Summaries complete")

        doc_json = convert_keys(asdict(lumi_doc), "snake_to_camel")
        summaries_json = convert_keys(asdict(lumi_doc.summaries), "snake_to_camel")
        db.save_lumi_doc(job.arxiv_id, metadata.version, doc_json, summaries_json)

        storage = get_storage_client()
        base_path = f"papers/{job.arxiv_id}/v{metadata.version}"
        doc_path = f"{base_path}/lumi_doc.json"
        summaries_path = f"{base_path}/summaries.json"
        try:
            storage.upload_json(doc_path, doc_json)
            storage.upload_json(summaries_path, summaries_json)
            logger.info(
                f"[{job.job_id}] Uploaded lumi_doc to {doc_path} and summaries to {summaries_path}"
            )
        except Exception as e:
            logger.exception(f"[{job.job_id}] Failed to upload JSON to storage: {e}")
            # Continue even if uploads fail, but mark progress accordingly.
            db.update_job_progress(
                job.job_id,
                status=LoadingStatus.ERROR_DOCUMENT_LOAD,
                stage="UPLOAD_ERROR",
                progress_percent=0.9,
            )
            raise

        db.update_job_progress(
            job.job_id,
            status=LoadingStatus.SUCCESS,
            stage="SUCCESS",
            progress_percent=1.0,
        )
    except Exception:
        db.update_job_progress(
            job.job_id,
            status=LoadingStatus.ERROR_DOCUMENT_LOAD,
            stage="ERROR",
            progress_percent=0.0,
        )
        raise


def process_once(db: Optional[DbClient] = None) -> bool:
    """
    Deprecated helper kept for backward compatibility in tests.
    """
    return process_next(db=db, queue=None, block=False, timeout=None)


def process_next(
    *,
    db: Optional[DbClient] = None,
    queue: Optional[JobQueue] = None,
    block: bool = True,
    timeout: Optional[int] = None,
) -> bool:
    """
    Fetch and process one job from the queue (or DB fallback). Returns True if processed.
    """
    db = db or get_db_client()
    queue = queue or get_queue_client()

    job_id = queue.dequeue(block=block, timeout=timeout) if queue else None
    job: Optional[JobRecord] = None

    if job_id:
        job = db.get_job(job_id)
        if not job:
            logger.warning("Received job_id %s from queue but no DB record found", job_id)
            return False
        # Claim the job so other workers skip it.
        if hasattr(db, "claim_next_waiting_job"):
            # For Postgres, also ensure status flips to prevent reuse.
            if job.status == LoadingStatus.WAITING:
                claimed = db.claim_next_waiting_job()
                if claimed and claimed.job_id == job.job_id:
                    job = claimed
    else:
        # Fallback to legacy polling for any WAITING jobs that were never queued.
        job = db.claim_next_waiting_job() if hasattr(db, "claim_next_waiting_job") else db.fetch_next_waiting_job()
        if not job:
            return False

    process_job(job, db)
    return True


def run_loop(poll_interval_seconds: float = 2.0) -> None:
    """
    Simple polling loop that blocks on the queue. Intended to be run under systemd/supervisor.
    """
    db = get_db_client()
    queue = get_queue_client()
    while True:
        if hasattr(db, "requeue_stale_locks"):
            try:
                db.requeue_stale_locks(lock_timeout_seconds=900)
            except Exception:
                logger.exception("Failed to requeue stale locks")
        processed = process_next(db=db, queue=queue, block=True, timeout=int(poll_interval_seconds))
        if not processed:
            time.sleep(poll_interval_seconds)


if __name__ == "__main__":
    run_loop()
