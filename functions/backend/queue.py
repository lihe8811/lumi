"""
Queue abstraction for job dispatching.

Supports an in-memory fallback for tests/local runs and a Redis-backed
implementation for production.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

import redis
from redis import exceptions as redis_exceptions


class JobQueue(Protocol):
    """Minimal queue interface for dispatching job_ids to workers."""

    def enqueue(self, job_id: str) -> None:
        ...

    def dequeue(self, *, block: bool = True, timeout: int | None = None) -> Optional[str]:
        ...


@dataclass
class InMemoryJobQueue:
    """Simple FIFO queue for testing/dev."""

    items: list[str] = field(default_factory=list)

    def enqueue(self, job_id: str) -> None:
        self.items.append(job_id)

    def dequeue(self, *, block: bool = True, timeout: int | None = None) -> Optional[str]:
        if not self.items:
            return None
        return self.items.pop(0)


@dataclass
class RedisJobQueue:
    """Redis-backed queue using list push/pop operations."""

    url: str
    queue_key: str = "lumi:jobs"

    def __post_init__(self):
        self.client = redis.Redis.from_url(self.url)

    def enqueue(self, job_id: str) -> None:
        self.client.rpush(self.queue_key, job_id)

    def dequeue(self, *, block: bool = True, timeout: int | None = None) -> Optional[str]:
        try:
            if block:
                result = self.client.blpop(self.queue_key, timeout=timeout or 0)
                if result is None:
                    return None
                _, job_id = result
            else:
                job_id = self.client.lpop(self.queue_key)
                if job_id is None:
                    return None
            return job_id.decode("utf-8")
        except redis_exceptions.ConnectionError:
            # Connection resets can happen on managed Redis. Treat as empty queue
            # and allow the worker loop to retry.
            self.client = redis.Redis.from_url(self.url)
            return None
