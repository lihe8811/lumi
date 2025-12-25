"""
HTTP routes for the refactored backend API.
"""

from __future__ import annotations

import time
import os
import tempfile
import re
import io
from uuid import uuid4
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form

from backend.dependencies import (
    get_arxiv_sanity_store,
    get_db_client,
    get_queue_client,
    get_storage_client,
)
from backend.arxiv_sanity import DEFAULT_PAGE_SIZE
from backend.db import DbClient, FeedbackRecord
from backend.queue import JobQueue
from backend.schemas import LumiDocResponse
from backend.schemas import (
    AnswerRequest,
    AnswerResponse,
    FeedbackRequest,
    FeedbackResponse,
    JobStatusResponse,
    MetadataRequest,
    MetadataResponse,
    PersonalSummaryRequest,
    PersonalSummaryResponse,
    RequestImportPayload,
    RequestImportResponse,
    SignUrlResponse,
    ListPapersResponse,
    PaperSummary,
    ArxivSearchResponse,
)
from backend.arxiv_sanity import ArxivSanityStore
from backend.storage import StorageClient
from backend.config import get_settings
from models import api_config
from shared.types import LoadingStatus

import logging

logger = logging.getLogger(__name__)

router = APIRouter()


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _extract_pdf_title_for_dedupe(pdf_bytes: bytes, fallback: str) -> str:
    try:
        from pdfminer.high_level import extract_text

        first_page = extract_text(io.BytesIO(pdf_bytes), page_numbers=[0]) or ""
    except Exception:
        first_page = ""

    lines = [re.sub(r"\s+", " ", line).strip() for line in first_page.splitlines()]
    lines = [line for line in lines if line]
    for line in lines[:6]:
        if len(re.findall(r"\w+", line)) >= 4:
            return line
    return fallback


def _find_existing_paper_by_title(db: DbClient, title: str) -> dict | None:
    normalized = _normalize_title(title)
    if not normalized:
        return None
    for arxiv_id, version, metadata in db.list_docs(limit=500):
        meta_title = _normalize_title((metadata or {}).get("title", ""))
        if meta_title and meta_title == normalized:
            return {"arxiv_id": arxiv_id, "version": version}
    return None


def _generate_local_arxiv_id(db: DbClient) -> str:
    prefix = datetime.now(timezone.utc).strftime("%y%m")
    local_prefix = f"{prefix}.L"
    existing_ids = db.list_metadata_ids(local_prefix)
    max_seq = 0
    for arxiv_id in existing_ids:
        match = re.match(rf"{re.escape(local_prefix)}(\\d{{4}})$", arxiv_id)
        if match:
            max_seq = max(max_seq, int(match.group(1)))
    next_seq = max_seq + 1
    return f"{local_prefix}{next_seq:04d}"


@router.post(
    "/request_arxiv_doc_import", response_model=RequestImportResponse, status_code=202
)
def request_arxiv_doc_import(
    payload: RequestImportPayload,
    db: DbClient = Depends(get_db_client),
    queue: JobQueue = Depends(get_queue_client),
):
    """
    Enqueue an import job. The worker will handle the heavy lifting.
    """
    if re.match(r"^\d{4}\.L\d{4}$", payload.arxiv_id):
        raise HTTPException(
            status_code=400,
            detail="Local uploads must use /api/request_local_pdf_import",
        )
    job = db.create_import_job(payload.arxiv_id, payload.version)
    if payload.test_config:
        db.save_metadata(payload.arxiv_id, {"test_config": payload.test_config})
    queue.enqueue(job.job_id)
    return RequestImportResponse(
        job_id=job.job_id,
        arxiv_id=job.arxiv_id,
        version=job.version,
        status=job.status.name,
    )


@router.post(
    "/request_local_pdf_import", response_model=RequestImportResponse, status_code=202
)
async def request_local_pdf_import(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    authors: str | None = Form(None),
    summary: str | None = Form(None),
    db: DbClient = Depends(get_db_client),
    queue: JobQueue = Depends(get_queue_client),
    storage: StorageClient = Depends(get_storage_client),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF file required")

    pdf_bytes = await file.read()
    title_candidate = _extract_pdf_title_for_dedupe(
        pdf_bytes, file.filename or "Uploaded PDF"
    )
    existing = _find_existing_paper_by_title(db, title_candidate)
    if existing:
        job = db.create_import_job(existing["arxiv_id"], existing["version"])
        db.update_job_progress(
            job.job_id,
            status=LoadingStatus.SUCCESS,
            stage="DEDUPED",
            progress_percent=1.0,
        )
        return RequestImportResponse(
            job_id=job.job_id,
            arxiv_id=job.arxiv_id,
            version=job.version,
            status=LoadingStatus.SUCCESS.name,
        )

    arxiv_id = _generate_local_arxiv_id(db)
    version = "1"
    job = db.create_import_job(arxiv_id, version)

    storage_path = f"papers/{arxiv_id}/v{version}/source.pdf"
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as temp_file:
        temp_file.write(pdf_bytes)
        temp_file.flush()
        storage.upload_file(temp_file.name, storage_path)

    metadata_payload = {
        "storage_pdf_path": storage_path,
        "source_filename": file.filename,
        "title_hint": title or title_candidate,
        "authors_hint": authors,
        "summary_hint": summary,
    }
    db.save_metadata(arxiv_id, metadata_payload)
    queue.enqueue(job.job_id)

    return RequestImportResponse(
        job_id=job.job_id,
        arxiv_id=job.arxiv_id,
        version=job.version,
        status=job.status.name,
    )


@router.get("/job-status/{job_id}", response_model=JobStatusResponse)
def job_status(job_id: str, db: DbClient = Depends(get_db_client)):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status.name,
        arxiv_id=job.arxiv_id,
        version=job.version,
        stage=job.stage,
        progress_percent=job.progress_percent,
    )


@router.post("/get_arxiv_metadata", response_model=MetadataResponse)
def get_arxiv_metadata(
    payload: MetadataRequest, db: DbClient = Depends(get_db_client)
):
    metadata = db.get_metadata(payload.arxiv_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="Metadata not found")
    return MetadataResponse(arxiv_id=payload.arxiv_id, metadata=metadata)


@router.post("/get_lumi_response", response_model=AnswerResponse)
def get_lumi_response(
    payload: AnswerRequest, db: DbClient = Depends(get_db_client)
):
    """
    Placeholder implementation returning a stub answer.
    """
    answer = {
        "id": uuid4().hex,
        "query": payload.query,
        "highlight": payload.highlight,
        "timestamp": int(time.time() * 1000),
        "response_content": [],
    }
    return AnswerResponse(
        arxiv_id=payload.arxiv_id, version=payload.version, answer=answer
    )


@router.post("/get_personal_summary", response_model=PersonalSummaryResponse)
def get_personal_summary(
    payload: PersonalSummaryRequest, db: DbClient = Depends(get_db_client)
):
    summary = {
        "id": uuid4().hex,
        "content": [],
        "timestamp": int(time.time() * 1000),
    }
    return PersonalSummaryResponse(
        arxiv_id=payload.arxiv_id, version=payload.version, summary=summary
    )


@router.post("/save_user_feedback", response_model=FeedbackResponse)
def save_user_feedback(
    payload: FeedbackRequest, db: DbClient = Depends(get_db_client)
):
    record = FeedbackRecord(
        arxiv_id=payload.arxiv_id,
        version=payload.version,
        user_feedback_text=payload.user_feedback_text,
    )
    db.save_feedback(record)
    return FeedbackResponse(status="ok")


@router.get("/sign-url", response_model=SignUrlResponse)
def sign_url(
    path: str = Query(..., description="Object path in storage"),
    op: str = Query("get", pattern="^(get|put)$"),
    expires_in: int = Query(3600, ge=60, le=86400),
    storage: StorageClient = Depends(get_storage_client),
):
    if op == "get":
        url = storage.presign_get(path, expires_in=expires_in)
    else:
        url = storage.presign_put(path, expires_in=expires_in)
    return SignUrlResponse(url=url)


@router.get("/list-papers", response_model=ListPapersResponse)
def list_papers(db: DbClient = Depends(get_db_client)):
    docs = db.list_docs(limit=100)
    papers = []
    for arxiv_id, version, metadata in docs:
        meta = metadata or {}
        # Ensure required fields exist for the frontend.
        meta.setdefault("paperId", arxiv_id)
        meta.setdefault("version", version)
        papers.append(PaperSummary(arxiv_id=arxiv_id, version=version, metadata=meta))
    return ListPapersResponse(papers=papers)


@router.get("/arxiv-sanity/recent", response_model=ArxivSearchResponse)
def list_recent_arxiv(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=100),
    categories: str | None = Query(None),
    store: ArxivSanityStore = Depends(get_arxiv_sanity_store),
):
    offset = (page - 1) * page_size
    category_list = (
        [c.strip() for c in categories.split(",") if c.strip()]
        if categories
        else None
    )
    papers, total = store.list_recent(
        limit=page_size, offset=offset, categories=category_list
    )
    payload = [
        {"metadata": paper.to_metadata(), "score": None} for paper in papers
    ]
    return ArxivSearchResponse(
        papers=payload, total=total, page=page, page_size=page_size
    )


@router.get("/arxiv-sanity/search", response_model=ArxivSearchResponse)
def search_arxiv(
    query: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=100),
    categories: str | None = Query(None),
    store: ArxivSanityStore = Depends(get_arxiv_sanity_store),
):
    offset = (page - 1) * page_size
    category_list = (
        [c.strip() for c in categories.split(",") if c.strip()]
        if categories
        else None
    )
    results, total = store.search(
        query, limit=page_size, offset=offset, categories=category_list
    )
    payload = [
        {"metadata": paper.to_metadata(), "score": score}
        for paper, score in results
    ]
    return ArxivSearchResponse(
        papers=payload, total=total, page=page, page_size=page_size
    )


@router.get("/lumi-doc/{arxiv_id}/{version}", response_model=LumiDocResponse)
def get_lumi_doc(
    arxiv_id: str,
    version: str,
    db: DbClient = Depends(get_db_client),
):
    doc_tuple = db.get_lumi_doc(arxiv_id, version)
    if not doc_tuple:
        raise HTTPException(status_code=404, detail="Document not found")
    doc_json, summaries_json = doc_tuple
    return LumiDocResponse(
        arxiv_id=arxiv_id,
        version=version,
        doc=doc_json,
        summaries=summaries_json,
    )
