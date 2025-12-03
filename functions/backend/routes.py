"""
HTTP routes for the refactored backend API.
"""

from __future__ import annotations

import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.dependencies import get_db_client, get_queue_client, get_storage_client
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
)
from backend.storage import StorageClient
from shared.types import LoadingStatus

router = APIRouter()


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
