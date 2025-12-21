"""
Lightweight arXiv ingestion + search store inspired by arxiv-sanity-lite.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import sqlite3
import time
import urllib.request
from typing import Iterable, Sequence

import feedparser

DEFAULT_QUERY = (
    "cat:cs.CV+OR+cat:cs.LG+OR+cat:cs.CL+OR+cat:cs.AI+OR+cat:cs.NE+OR+cat:cs.RO"
)
DEFAULT_PAGE_SIZE = 25


@dataclass(frozen=True)
class ArxivPaper:
    paper_id: str
    version: str
    title: str
    summary: str
    authors: list[str]
    updated_timestamp: str
    published_timestamp: str
    updated_time: float
    published_time: float
    categories: list[str]

    def to_metadata(self) -> dict:
        return {
            "paperId": self.paper_id,
            "version": self.version,
            "authors": self.authors,
            "title": self.title,
            "summary": self.summary,
            "updatedTimestamp": self.updated_timestamp,
            "publishedTimestamp": self.published_timestamp,
            "categories": self.categories,
        }


def _parse_arxiv_url(url: str) -> tuple[str, str, int]:
    ix = url.rfind("/")
    if ix < 0:
        raise ValueError(f"bad url: {url}")
    idv = url[ix + 1 :]
    parts = idv.split("v")
    if len(parts) != 2:
        raise ValueError(f"bad id/version in url: {url}")
    return idv, parts[0], int(parts[1])


def _encode_feedparser_dict(value):
    if isinstance(value, (feedparser.FeedParserDict, dict)):
        return {k: _encode_feedparser_dict(value[k]) for k in value.keys()}
    if isinstance(value, list):
        return [_encode_feedparser_dict(item) for item in value]
    return value


def _fetch_arxiv_batch(search_query: str, start_index: int = 0) -> Sequence[ArxivPaper]:
    base_url = "http://export.arxiv.org/api/query?"
    add_url = (
        "search_query=%s&sortBy=lastUpdatedDate&start=%d&max_results=100"
        % (search_query, start_index)
    )
    with urllib.request.urlopen(base_url + add_url, timeout=30) as url:
        response = url.read()
    parse = feedparser.parse(response)
    papers: list[ArxivPaper] = []
    for entry in parse.entries:
        data = _encode_feedparser_dict(entry)
        idv, raw_id, version = _parse_arxiv_url(data["id"])
        authors = [a["name"] for a in data.get("authors", [])]
        tags = [t.get("term") for t in data.get("tags", []) if t.get("term")]
        updated_parsed = data.get("updated_parsed")
        published_parsed = data.get("published_parsed")
        updated_time = time.mktime(updated_parsed) if updated_parsed else 0.0
        published_time = time.mktime(published_parsed) if published_parsed else 0.0
        papers.append(
            ArxivPaper(
                paper_id=raw_id,
                version=str(version),
                title=data.get("title", "").strip().replace("\n", " "),
                summary=data.get("summary", "").strip().replace("\n", " "),
                authors=authors,
                updated_timestamp=data.get("updated", ""),
                published_timestamp=data.get("published", ""),
                updated_time=updated_time,
                published_time=published_time,
                categories=tags,
            )
        )
    return papers


class ArxivSanityStore:
    def __init__(self, data_dir: str):
        os.makedirs(data_dir, exist_ok=True)
        self.db_path = os.path.join(data_dir, "arxiv_sanity.db")
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS papers (
                    paper_id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    authors_json TEXT NOT NULL,
                    updated_timestamp TEXT NOT NULL,
                    published_timestamp TEXT NOT NULL,
                    updated_time REAL NOT NULL,
                    published_time REAL NOT NULL,
                    categories_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_papers_updated_time ON papers(updated_time DESC)"
            )

    def upsert_papers(self, papers: Iterable[ArxivPaper]) -> int:
        updated = 0
        with self._connect() as conn:
            for paper in papers:
                row = conn.execute(
                    "SELECT updated_time FROM papers WHERE paper_id = ?",
                    (paper.paper_id,),
                ).fetchone()
                if row and paper.updated_time <= row["updated_time"]:
                    continue
                conn.execute(
                    """
                    INSERT INTO papers (
                        paper_id,
                        version,
                        title,
                        summary,
                        authors_json,
                        updated_timestamp,
                        published_timestamp,
                        updated_time,
                        published_time,
                        categories_json,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(paper_id) DO UPDATE SET
                        version = excluded.version,
                        title = excluded.title,
                        summary = excluded.summary,
                        authors_json = excluded.authors_json,
                        updated_timestamp = excluded.updated_timestamp,
                        published_timestamp = excluded.published_timestamp,
                        updated_time = excluded.updated_time,
                        published_time = excluded.published_time,
                        categories_json = excluded.categories_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        paper.paper_id,
                        paper.version,
                        paper.title,
                        paper.summary,
                        json.dumps(paper.authors),
                        paper.updated_timestamp,
                        paper.published_timestamp,
                        paper.updated_time,
                        paper.published_time,
                        json.dumps(paper.categories),
                        time.time(),
                    ),
                )
                updated += 1
        return updated

    def list_recent(
        self,
        *,
        limit: int,
        offset: int = 0,
        categories: list[str] | None = None,
    ) -> tuple[list[ArxivPaper], int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM papers
                ORDER BY updated_time DESC
                """
            ).fetchall()
        papers = [self._row_to_paper(row) for row in rows]
        if categories:
            wanted = {c.strip() for c in categories if c.strip()}
            papers = [
                paper
                for paper in papers
                if wanted.intersection(paper.categories)
            ]
        total = len(papers)
        return papers[offset : offset + limit], total

    def search(
        self,
        query: str,
        *,
        limit: int,
        offset: int = 0,
        categories: list[str] | None = None,
    ) -> tuple[list[tuple[ArxivPaper, float]], int]:
        if not query.strip():
            return [], 0
        qs = query.lower().strip().split()
        wanted = {c.strip() for c in categories} if categories else set()

        def score_row(row: sqlite3.Row) -> float:
            title = row["title"].lower()
            summary = row["summary"].lower()
            authors = " ".join(json.loads(row["authors_json"])).lower()
            match = lambda s: sum(min(3, s.count(q)) for q in qs)
            matchu = lambda s: sum(int(s.count(q) > 0) for q in qs)
            score = 0.0
            score += 10.0 * matchu(authors)
            score += 20.0 * matchu(title)
            score += 1.0 * match(summary)
            return score

        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM papers").fetchall()
        scored: list[tuple[float, ArxivPaper]] = []
        for row in rows:
            paper = self._row_to_paper(row)
            if wanted and not wanted.intersection(paper.categories):
                continue
            score = score_row(row)
            if score > 0:
                scored.append((score, paper))
        scored.sort(key=lambda item: item[0], reverse=True)
        total = len(scored)
        page = scored[offset : offset + limit]
        return [(paper, score) for score, paper in page], total

    def ingest(
        self,
        *,
        query: str = DEFAULT_QUERY,
        num: int = 200,
        start: int = 0,
        break_after: int = 3,
    ) -> int:
        total_updated = 0
        zero_updates = 0
        for k in range(start, start + num, 100):
            papers = _fetch_arxiv_batch(query, start_index=k)
            updated = self.upsert_papers(papers)
            total_updated += updated
            if updated == 0:
                zero_updates += 1
                if break_after and zero_updates >= break_after:
                    break
            else:
                zero_updates = 0
            time.sleep(1)
        return total_updated

    def _row_to_paper(self, row: sqlite3.Row) -> ArxivPaper:
        return ArxivPaper(
            paper_id=row["paper_id"],
            version=row["version"],
            title=row["title"],
            summary=row["summary"],
            authors=json.loads(row["authors_json"]),
            updated_timestamp=row["updated_timestamp"],
            published_timestamp=row["published_timestamp"],
            updated_time=row["updated_time"],
            published_time=row["published_time"],
            categories=json.loads(row["categories_json"]),
        )
