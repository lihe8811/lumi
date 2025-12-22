"""
Database abstraction for Postgres and an in-memory test implementation.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Protocol

from sqlalchemy import JSON, Column, Float, String, create_engine, select
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from shared.types import LoadingStatus


class DbClient(Protocol):
    """Interface for database access."""

    def create_import_job(
        self, arxiv_id: str, version: str | None = None
    ) -> "JobRecord":
        ...

    def get_job(self, job_id: str) -> Optional["JobRecord"]:
        ...

    def claim_next_waiting_job(self) -> Optional["JobRecord"]:
        ...

    def save_metadata(self, arxiv_id: str, metadata: dict) -> None:
        ...

    def get_metadata(self, arxiv_id: str) -> Optional[dict]:
        ...

    def save_feedback(self, feedback: "FeedbackRecord") -> None:
        ...

    def fetch_next_waiting_job(self) -> Optional["JobRecord"]:
        ...

    def update_job_status(self, job_id: str, status: LoadingStatus) -> None:
        ...

    def update_job_progress(
        self,
        job_id: str,
        *,
        status: Optional[LoadingStatus] = None,
        stage: Optional[str] = None,
        progress_percent: Optional[float] = None,
    ) -> None:
        ...

    def save_lumi_doc(
        self, arxiv_id: str, version: str, doc_json: dict, summaries_json: dict
    ) -> None:
        ...

    def get_lumi_doc(
        self, arxiv_id: str, version: str
    ) -> Optional[tuple[dict, dict]]:
        ...

    def list_docs(self, limit: int = 100) -> list[tuple[str, str, dict]]:
        ...

    def requeue_stale_locks(self, lock_timeout_seconds: float = 600) -> int:
        ...


@dataclass
class JobRecord:
    job_id: str
    arxiv_id: str
    version: Optional[str]
    status: LoadingStatus
    stage: str = "WAITING"
    progress_percent: float = 0.0
    locked_at: Optional[float] = None
    created_at: float = field(default_factory=lambda: time.time())
    updated_at: float = field(default_factory=lambda: time.time())

    def as_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "arxiv_id": self.arxiv_id,
            "version": self.version,
            "status": self.status.name,
            "stage": self.stage,
            "progress_percent": self.progress_percent,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class FeedbackRecord:
    arxiv_id: Optional[str]
    version: Optional[str]
    user_feedback_text: str
    created_at: float = field(default_factory=lambda: time.time())

    def as_dict(self) -> dict:
        return {
            "arxiv_id": self.arxiv_id,
            "version": self.version,
            "user_feedback_text": self.user_feedback_text,
            "created_at": self.created_at,
        }


class InMemoryDbClient:
    """Simple in-memory database for development and tests."""

    def __init__(self):
        self.jobs: Dict[str, JobRecord] = {}
        self.metadata: Dict[str, dict] = {}
        self.feedback: Dict[str, FeedbackRecord] = {}
        self.docs: Dict[tuple[str, str], tuple[dict, dict]] = {}
        self.locked: set[str] = set()

    def create_import_job(
        self, arxiv_id: str, version: str | None = None
    ) -> JobRecord:
        job_id = uuid.uuid4().hex
        record = JobRecord(
            job_id=job_id,
            arxiv_id=arxiv_id,
            version=version,
            status=LoadingStatus.WAITING,
        )
        self.jobs[job_id] = record
        return record

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        return self.jobs.get(job_id)

    def save_metadata(self, arxiv_id: str, metadata: dict) -> None:
        self.metadata[arxiv_id] = metadata

    def get_metadata(self, arxiv_id: str) -> Optional[dict]:
        return self.metadata.get(arxiv_id)

    def save_feedback(self, feedback: FeedbackRecord) -> None:
        key = uuid.uuid4().hex
        self.feedback[key] = feedback

    def reset(self) -> None:
        """Clear all stored data (useful in tests)."""
        self.jobs.clear()
        self.metadata.clear()
        self.feedback.clear()
        self.docs.clear()

    def fetch_next_waiting_job(self) -> Optional[JobRecord]:
        for job in self.jobs.values():
            if job.status == LoadingStatus.WAITING:
                return job
        return None

    def claim_next_waiting_job(self) -> Optional[JobRecord]:
        for job in self.jobs.values():
            if job.status == LoadingStatus.WAITING and job.job_id not in self.locked:
                job.status = LoadingStatus.SUMMARIZING
                job.locked_at = time.time()
                self.locked.add(job.job_id)
                return job
        return None

    def update_job_status(self, job_id: str, status: LoadingStatus) -> None:
        job = self.jobs.get(job_id)
        if job:
            job.status = status
            job.updated_at = time.time()

    def update_job_progress(
        self,
        job_id: str,
        *,
        status: Optional[LoadingStatus] = None,
        stage: Optional[str] = None,
        progress_percent: Optional[float] = None,
    ) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return
        if status:
            job.status = status
        if stage:
            job.stage = stage
        if progress_percent is not None:
            job.progress_percent = progress_percent
        job.updated_at = time.time()

    def save_lumi_doc(
        self, arxiv_id: str, version: str, doc_json: dict, summaries_json: dict
    ) -> None:
        self.docs[(arxiv_id, version)] = (doc_json, summaries_json)

    def get_lumi_doc(
        self, arxiv_id: str, version: str
    ) -> Optional[tuple[dict, dict]]:
        return self.docs.get((arxiv_id, version))

    def list_docs(self, limit: int = 100) -> list[tuple[str, str, dict]]:
        items: list[tuple[str, str, dict]] = []
        for (arxiv_id, version), (doc_json, summaries_json) in self.docs.items():
            meta = doc_json.get("metadata", {})
            items.append((arxiv_id, version, meta))
            if len(items) >= limit:
                break
        return items

    def requeue_stale_locks(self, lock_timeout_seconds: float = 600) -> int:
        now = time.time()
        requeued = 0
        for job in self.jobs.values():
            if (
                job.status == LoadingStatus.SUMMARIZING
                and job.stage == "CLAIMED"
                and job.locked_at
                and now - job.locked_at > lock_timeout_seconds
            ):
                job.status = LoadingStatus.WAITING
                job.stage = "WAITING"
                job.progress_percent = 0.0
                job.locked_at = None
                job.updated_at = now
                requeued += 1
        return requeued


class PostgresDbClient:
    """
    SQLAlchemy-backed implementation. Accepts any SQLAlchemy URL (e.g., Postgres or SQLite for tests).
    """

    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("DATABASE_URL is required for PostgresDbClient")
        self.engine = create_engine(
            database_url,
            future=True,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        self.Session = sessionmaker(
            bind=self.engine, class_=Session, expire_on_commit=False, future=True
        )
        Base.metadata.create_all(self.engine)

    def _to_job_record(self, job: "JobRow") -> JobRecord:
        return JobRecord(
            job_id=job.job_id,
            arxiv_id=job.arxiv_id,
            version=job.version,
            status=LoadingStatus(job.status),
            stage=job.stage,
            progress_percent=job.progress_percent,
            locked_at=job.locked_at,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    def create_import_job(
        self, arxiv_id: str, version: str | None = None
    ) -> JobRecord:
        now = time.time()
        job_id = uuid.uuid4().hex
        with self.Session() as session:
            job = JobRow(
                job_id=job_id,
                arxiv_id=arxiv_id,
                version=version,
                status=LoadingStatus.WAITING.value,
                stage="WAITING",
                progress_percent=0.0,
                created_at=now,
                updated_at=now,
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            return self._to_job_record(job)

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        with self.Session() as session:
            job = session.get(JobRow, job_id)
            if not job:
                return None
            return self._to_job_record(job)

    def fetch_next_waiting_job(self) -> Optional[JobRecord]:
        with self.Session() as session:
            stmt = (
                select(JobRow)
                .where(JobRow.status == LoadingStatus.WAITING.value)
                .order_by(JobRow.created_at.asc())
                .limit(1)
            )
            job = session.execute(stmt).scalar_one_or_none()
            if not job:
                return None
            return self._to_job_record(job)

    def claim_next_waiting_job(self) -> Optional[JobRecord]:
        now = time.time()
        with self.Session() as session:
            stmt = (
                select(JobRow)
                .where(JobRow.status == LoadingStatus.WAITING.value)
                .order_by(JobRow.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            job = session.execute(stmt).scalar_one_or_none()
            if not job:
                return None
            job.status = LoadingStatus.SUMMARIZING.value
            job.stage = "CLAIMED"
            job.locked_at = now
            job.updated_at = now
            session.commit()
            session.refresh(job)
            return self._to_job_record(job)

    def requeue_stale_locks(self, lock_timeout_seconds: float = 600) -> int:
        cutoff = time.time() - lock_timeout_seconds
        with self.Session() as session:
            updated = (
                session.query(JobRow)
                .filter(
                    JobRow.status == LoadingStatus.SUMMARIZING.value,
                    JobRow.stage == "CLAIMED",
                    JobRow.locked_at != None,
                    JobRow.locked_at < cutoff,
                )
                .update(
                    {
                        JobRow.status: LoadingStatus.WAITING.value,
                        JobRow.stage: "WAITING",
                        JobRow.progress_percent: 0.0,
                        JobRow.locked_at: None,
                        JobRow.updated_at: time.time(),
                    },
                    synchronize_session=False,
                )
            )
            session.commit()
            return updated or 0

    def update_job_status(self, job_id: str, status: LoadingStatus) -> None:
        with self.Session() as session:
            job = session.get(JobRow, job_id)
            if not job:
                return
            job.status = status.value
            job.updated_at = time.time()
            session.commit()

    def update_job_progress(
        self,
        job_id: str,
        *,
        status: Optional[LoadingStatus] = None,
        stage: Optional[str] = None,
        progress_percent: Optional[float] = None,
    ) -> None:
        with self.Session() as session:
            job = session.get(JobRow, job_id)
            if not job:
                return
            if status:
                job.status = status.value
            if stage:
                job.stage = stage
            if progress_percent is not None:
                job.progress_percent = progress_percent
            job.updated_at = time.time()
            session.commit()

    def save_metadata(self, arxiv_id: str, metadata: dict) -> None:
        with self.Session() as session:
            existing = session.get(MetadataRow, arxiv_id)
            if existing:
                existing.data = metadata
            else:
                session.add(
                    MetadataRow(arxiv_id=arxiv_id, data=metadata)
                )
            session.commit()

    def get_metadata(self, arxiv_id: str) -> Optional[dict]:
        with self.Session() as session:
            row = session.get(MetadataRow, arxiv_id)
            return row.data if row else None

    def save_feedback(self, feedback: FeedbackRecord) -> None:
        with self.Session() as session:
            row = FeedbackRow(
                id=uuid.uuid4().hex,
                arxiv_id=feedback.arxiv_id,
                version=feedback.version,
                user_feedback_text=feedback.user_feedback_text,
                created_at=feedback.created_at,
            )
            session.add(row)
            session.commit()

    def save_lumi_doc(
        self, arxiv_id: str, version: str, doc_json: dict, summaries_json: dict
    ) -> None:
        with self.Session() as session:
            row = session.get(PaperVersionRow, (arxiv_id, version))
            if row:
                row.lumi_doc = doc_json
                row.summaries = summaries_json
                row.updated_at = time.time()
            else:
                session.add(
                    PaperVersionRow(
                        arxiv_id=arxiv_id,
                        version=version,
                        lumi_doc=doc_json,
                        summaries=summaries_json,
                        updated_at=time.time(),
                    )
                )
            session.commit()

    def get_lumi_doc(
        self, arxiv_id: str, version: str
    ) -> Optional[tuple[dict, dict]]:
        with self.Session() as session:
            row = session.get(PaperVersionRow, (arxiv_id, version))
            if not row:
                return None
            return row.lumi_doc, row.summaries

    def list_docs(self, limit: int = 100) -> list[tuple[str, str, dict]]:
        with self.Session() as session:
            rows = (
                session.query(PaperVersionRow)
                .order_by(PaperVersionRow.updated_at.desc())
                .limit(limit)
                .all()
            )
            results: list[tuple[str, str, dict]] = []
            for row in rows:
                meta = row.lumi_doc.get("metadata", {}) if row.lumi_doc else {}
                results.append((row.arxiv_id, row.version, meta))
            return results


Base = declarative_base()


class JobRow(Base):
    __tablename__ = "jobs"

    job_id = Column(String, primary_key=True)
    arxiv_id = Column(String, nullable=False, index=True)
    version = Column(String, nullable=True)
    status = Column(String, nullable=False, index=True)
    stage = Column(String, nullable=False, default="WAITING")
    progress_percent = Column(Float, nullable=False, default=0.0)
    locked_at = Column(Float, nullable=True)
    created_at = Column(Float, nullable=False)
    updated_at = Column(Float, nullable=False)


class MetadataRow(Base):
    __tablename__ = "paper_metadata"

    arxiv_id = Column(String, primary_key=True)
    data = Column("metadata", JSON, nullable=False)


class FeedbackRow(Base):
    __tablename__ = "user_feedback"

    id = Column(String, primary_key=True)
    arxiv_id = Column(String, nullable=True, index=True)
    version = Column(String, nullable=True)
    user_feedback_text = Column(String, nullable=False)
    created_at = Column(Float, nullable=False)


class PaperVersionRow(Base):
    __tablename__ = "paper_versions"

    arxiv_id = Column(String, primary_key=True)
    version = Column(String, primary_key=True)
    lumi_doc = Column(JSON, nullable=False)
    summaries = Column(JSON, nullable=False)
    updated_at = Column(Float, nullable=False)
