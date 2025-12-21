"""
Dependency wiring for the FastAPI app.
"""

from __future__ import annotations

from backend.config import get_settings
from backend.arxiv_sanity import ArxivSanityStore
from backend.db import DbClient, InMemoryDbClient, PostgresDbClient
from backend.queue import InMemoryJobQueue, JobQueue, RedisJobQueue
from backend.storage import CosStorageClient, InMemoryStorageClient, StorageClient

_db_client: DbClient | None = None
_storage_client: StorageClient | None = None
_queue_client: JobQueue | None = None
_arxiv_sanity_store: ArxivSanityStore | None = None


def get_db_client() -> DbClient:
    """
    Return a singleton DB client so job/status state persists across requests.
    """
    global _db_client
    if _db_client:
        return _db_client

    settings = get_settings()
    if settings.use_in_memory_backends or not settings.database_url:
        _db_client = InMemoryDbClient()
    else:
        try:
            _db_client = PostgresDbClient(settings.database_url)
        except NotImplementedError:
            # Until PostgresDbClient is implemented, fall back to in-memory.
            _db_client = InMemoryDbClient()
    return _db_client


def get_storage_client() -> StorageClient:
    global _storage_client
    if _storage_client:
        return _storage_client

    settings = get_settings()
    if settings.use_in_memory_backends or not settings.cos_bucket:
        _storage_client = InMemoryStorageClient()
    else:
        _storage_client = CosStorageClient(
            bucket=settings.cos_bucket,
            region=settings.cos_region or "",
            endpoint=settings.cos_endpoint or "",
            access_key_id=settings.aws_access_key_id or "",
            secret_access_key=settings.aws_secret_access_key or "",
        )
    return _storage_client


def get_queue_client() -> JobQueue:
    """
    Return a singleton queue client for dispatching jobs to workers.
    """
    global _queue_client
    if _queue_client:
        return _queue_client

    settings = get_settings()
    if settings.redis_url:
        _queue_client = RedisJobQueue(
            url=settings.redis_url,
            queue_key=settings.redis_queue_key,
        )
    else:
        _queue_client = InMemoryJobQueue()
    return _queue_client


def get_arxiv_sanity_store() -> ArxivSanityStore:
    global _arxiv_sanity_store
    if _arxiv_sanity_store:
        return _arxiv_sanity_store
    settings = get_settings()
    _arxiv_sanity_store = ArxivSanityStore(settings.arxiv_sanity_data_dir)
    return _arxiv_sanity_store
