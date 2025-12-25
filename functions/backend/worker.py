"""
Lightweight worker loop to process queued import jobs.

This is a placeholder/stub: it advances WAITING jobs to SUCCESS immediately.
Integrate the real import/summarization pipeline here in future steps.
"""

from __future__ import annotations

import time
import io
import re
from datetime import datetime, timezone
from dataclasses import asdict
from typing import Optional

from backend.db import DbClient, JobRecord
from backend.dependencies import get_db_client, get_queue_client, get_storage_client
from backend.storage import InMemoryStorageClient
from backend.config import get_settings
from import_pipeline import fetch_utils, import_pipeline, summaries
from models import extract_concepts as extract_concepts_util
from models import api_config
from backend.queue import JobQueue
from shared.types import ArxivMetadata, LoadingStatus
from shared.json_utils import convert_keys
import logging
import os
from pypdf import PdfReader
from pdfminer.high_level import extract_text

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

LOCAL_ID_PATTERN = re.compile(r"^\d{4}\.L\d{4}$")


def _is_local_id(arxiv_id: str) -> bool:
    return bool(LOCAL_ID_PATTERN.match(arxiv_id))

COMMON_HEADER_PATTERNS = (
    r"^\s*arxiv",
    r"^\s*preprint",
    r"^\s*draft",
    r"^\s*accepted",
    r"^\s*proceedings",
    r"^\s*copyright",
)


def _clean_pdf_lines(first_page: str) -> list[str]:
    lines = [re.sub(r"\s+", " ", line).strip() for line in first_page.splitlines()]
    return [line for line in lines if line]


def _find_abstract_text(first_page: str) -> str:
    match = re.search(
        r"(?is)\babstract\b[:\s\n]+(.*?)(?:\n\s*\n|\n\s*1\s+introduction|\n\s*i\.?\s+introduction|\n\s*keywords\b)",
        first_page,
    )
    return match.group(1).strip() if match else ""


def _extract_pdf_metadata(
    *,
    first_page: str,
    fallback_title: str,
    fallback_authors: str,
    fallback_abstract: str,
) -> tuple[str, str, str]:
    lines = _clean_pdf_lines(first_page)
    if not lines:
        return fallback_title, fallback_authors, fallback_abstract

    abstract_text = _find_abstract_text(first_page) or fallback_abstract
    abstract_index = None
    for i, line in enumerate(lines):
        if re.search(r"\babstract\b", line, flags=re.IGNORECASE):
            abstract_index = i
            break

    header_lines = lines[:abstract_index] if abstract_index is not None else lines[:6]
    header_lines = [
        line
        for line in header_lines
        if not any(re.match(pat, line, flags=re.IGNORECASE) for pat in COMMON_HEADER_PATTERNS)
    ]

    title = fallback_title
    author_raw = fallback_authors

    title_candidates = [
        line
        for line in header_lines
        if len(re.findall(r"\w+", line)) >= 4
        and not re.search(r"https?://|arxiv|doi", line, flags=re.IGNORECASE)
    ]
    if title_candidates:
        title = title_candidates[0]
    elif header_lines:
        title = header_lines[0]

    if header_lines:
        remaining = header_lines[1:4]
        author_candidates = [
            line
            for line in remaining
            if re.search(r",| and |\s&\s", line)
            and not re.search(r"university|institute|department|laboratory", line, flags=re.IGNORECASE)
        ]
        if author_candidates:
            author_raw = ", ".join(author_candidates)

    return title, author_raw, abstract_text


def process_job(job: JobRecord, db: DbClient) -> None:
    """
    Process a single job.

    In-memory mode (or missing DB/storage config): stub to SUCCESS.
    Otherwise, runs the import pipeline and marks status accordingly.
    """
    settings = get_settings()

    if _is_local_id(job.arxiv_id):
        storage = get_storage_client()
        metadata_payload = db.get_metadata(job.arxiv_id) or {}
        storage_path = metadata_payload.get("storage_pdf_path")
        if not storage_path:
            db.update_job_progress(
                job.job_id,
                status=LoadingStatus.ERROR_DOCUMENT_LOAD,
                stage="LOCAL_UPLOAD_MISSING_PDF",
                progress_percent=1.0,
            )
            logger.warning(
                "[%s] Local upload missing storage_pdf_path", job.job_id
            )
            return

        try:
            db.update_job_progress(
                job.job_id,
                status=LoadingStatus.SUMMARIZING,
                stage="FETCH_METADATA",
                progress_percent=0.05,
            )
            pdf_bytes = storage.get_bytes(storage_path)
            reader = PdfReader(io.BytesIO(pdf_bytes))
            info = reader.metadata or {}
            title = info.get("/Title") or ""
            author_raw = info.get("/Author") or ""
            abstract_text = ""
            try:
                first_page = extract_text(io.BytesIO(pdf_bytes), page_numbers=[0]) or ""
            except Exception:
                first_page = ""

            if first_page:
                title, author_raw, abstract_text = _extract_pdf_metadata(
                    first_page=first_page,
                    fallback_title=title,
                    fallback_authors=author_raw,
                    fallback_abstract=metadata_payload.get("summary_hint") or "",
                )

            if not title:
                title = metadata_payload.get("title_hint") or "Uploaded PDF"
            if not author_raw:
                author_raw = metadata_payload.get("authors_hint") or "Unknown"
            if not abstract_text:
                abstract_text = metadata_payload.get("summary_hint") or ""

            author_list = [
                a.strip() for a in author_raw.replace(";", ",").split(",") if a.strip()
            ] or ["Unknown"]
            now = datetime.now(timezone.utc).isoformat()
            metadata = ArxivMetadata(
                paper_id=job.arxiv_id,
                version=job.version or "1",
                authors=author_list,
                title=title,
                summary=abstract_text,
                updated_timestamp=now,
                published_timestamp=now,
            )
            db.save_metadata(job.arxiv_id, asdict(metadata))

            db.update_job_progress(
                job.job_id,
                status=LoadingStatus.SUMMARIZING,
                stage="IMPORT_PIPELINE",
                progress_percent=0.25,
            )
            concepts = extract_concepts_util.extract_concepts(metadata.summary)
            file_id = f"{metadata.paper_id}/v{metadata.version}"
            run_locally = isinstance(storage, InMemoryStorageClient)
            lumi_doc, image_path = import_pipeline.import_pdf_bytes(
                pdf_data=pdf_bytes,
                file_id=file_id,
                concepts=concepts or [],
                metadata=metadata,
                run_locally=run_locally,
                storage_client=storage,
            )
            logger.info(f"[{job.job_id}] Import pipeline complete (local)")

            db.update_job_progress(
                job.job_id,
                status=LoadingStatus.SUMMARIZING,
                stage="SUMMARIZING",
                progress_percent=0.7,
            )
            lumi_doc.summaries = summaries.generate_lumi_summaries(lumi_doc)
            doc_json = convert_keys(asdict(lumi_doc), "snake_to_camel")
            summaries_json = convert_keys(asdict(lumi_doc.summaries), "snake_to_camel")
            if image_path:
                metadata_payload = doc_json.get("metadata") or {}
                metadata_payload["featuredImage"] = {"imageStoragePath": image_path}
                doc_json["metadata"] = metadata_payload
            db.save_lumi_doc(job.arxiv_id, metadata.version, doc_json, summaries_json)

            base_path = f"papers/{job.arxiv_id}/v{metadata.version}"
            doc_path = f"{base_path}/lumi_doc.json"
            summaries_path = f"{base_path}/summaries.json"
            storage.upload_json(doc_path, doc_json)
            storage.upload_json(summaries_path, summaries_json)
            logger.info(
                f"[{job.job_id}] Uploaded lumi_doc to {doc_path} and summaries to {summaries_path}"
            )

            db.update_job_progress(
                job.job_id,
                status=LoadingStatus.SUCCESS,
                stage="SUCCESS",
                progress_percent=1.0,
            )
        except Exception as exc:
            logger.exception("[%s] Local upload failed: %s", job.job_id, exc)
            db.update_job_progress(
                job.job_id,
                status=LoadingStatus.ERROR_DOCUMENT_LOAD,
                stage="ERROR",
                progress_percent=0.0,
            )
        return

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
        storage = get_storage_client()
        logger.info("Storage client: %s", storage.__class__.__name__)
        run_locally = isinstance(storage, InMemoryStorageClient)

        lumi_doc, image_path = import_pipeline.import_arxiv_latex_and_pdf(
            arxiv_id=job.arxiv_id,
            version=metadata.version,
            concepts=concepts or [],
            metadata=metadata,
            run_locally=run_locally,
            storage_client=storage,
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
        if image_path:
            metadata_payload = doc_json.get("metadata") or {}
            metadata_payload["featuredImage"] = {
                "imageStoragePath": image_path
            }
            doc_json["metadata"] = metadata_payload
        summaries_json = convert_keys(asdict(lumi_doc.summaries), "snake_to_camel")
        db.save_lumi_doc(job.arxiv_id, metadata.version, doc_json, summaries_json)

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
