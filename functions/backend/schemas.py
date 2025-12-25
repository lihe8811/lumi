"""
Pydantic schemas for the refactored FastAPI backend.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class RequestImportPayload(BaseModel):
    arxiv_id: str = Field(..., max_length=64)
    version: Optional[str] = None
    test_config: Optional[dict] = None


class RequestImportResponse(BaseModel):
    job_id: str
    arxiv_id: str
    version: Optional[str]
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    arxiv_id: str
    version: Optional[str] = None
    stage: Optional[str] = None
    progress_percent: Optional[float] = None


class MetadataRequest(BaseModel):
    arxiv_id: str


class MetadataResponse(BaseModel):
    arxiv_id: str
    metadata: dict


class AnswerRequest(BaseModel):
    arxiv_id: str
    version: str
    query: Optional[str] = None
    highlight: Optional[str] = None
    highlighted_spans: Optional[list] = None
    image: Optional[dict] = None


class AnswerResponse(BaseModel):
    arxiv_id: str
    version: str
    answer: dict


class PersonalSummaryRequest(BaseModel):
    arxiv_id: str
    version: str
    past_papers: Optional[list] = None


class PersonalSummaryResponse(BaseModel):
    arxiv_id: str
    version: str
    summary: dict


class FeedbackRequest(BaseModel):
    arxiv_id: Optional[str] = None
    version: Optional[str] = None
    user_feedback_text: str = Field(..., max_length=1024)


class FeedbackResponse(BaseModel):
    status: Literal["ok"]


class SignUrlResponse(BaseModel):
    url: str


class LumiDocResponse(BaseModel):
    arxiv_id: str
    version: str
    doc: dict
    summaries: dict


class LumiDocSectionResponse(BaseModel):
    arxiv_id: str
    version: str
    section: dict


class PaperSummary(BaseModel):
    arxiv_id: str
    version: str
    metadata: dict | None = None


class ListPapersResponse(BaseModel):
    papers: list[PaperSummary]


class ArxivPaperMetadata(BaseModel):
    paperId: str
    version: str
    authors: list[str]
    title: str
    summary: str
    updatedTimestamp: str
    publishedTimestamp: str
    categories: list[str] | None = None


class ArxivSearchPaper(BaseModel):
    metadata: ArxivPaperMetadata
    score: Optional[float] = None


class ArxivSearchResponse(BaseModel):
    papers: list[ArxivSearchPaper]
    total: int
    page: int
    page_size: int
