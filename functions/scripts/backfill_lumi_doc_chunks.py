"""
Backfill Lumi doc index + section chunks to storage.

This reads existing lumi_doc JSON from the database and writes:
  - papers/{id}/v{version}/lumi_doc_index.json
  - papers/{id}/v{version}/sections/{section_id}.json
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.dependencies import get_db_client, get_storage_client
from backend.db import InMemoryDbClient, PostgresDbClient, PaperVersionRow
from backend.doc_chunks import build_doc_index, iter_section_chunks

logger = logging.getLogger(__name__)


def upload_chunks(
    *,
    arxiv_id: str,
    version: str,
    doc_json: dict,
    dry_run: bool,
) -> int:
    storage = get_storage_client()
    base_path = f"papers/{arxiv_id}/v{version}"
    doc_index_path = f"{base_path}/lumi_doc_index.json"
    sections_path = f"{base_path}/sections"

    section_count = 0
    if dry_run:
        return len(doc_json.get("sections") or [])

    doc_index = build_doc_index(doc_json)
    storage.upload_json(doc_index_path, doc_index)
    for section in iter_section_chunks(doc_json):
        section_id = section.get("id")
        if not section_id:
            continue
        storage.upload_json(f"{sections_path}/{section_id}.json", section)
        section_count += 1
    return section_count


def backfill_in_memory(db: InMemoryDbClient, *, dry_run: bool) -> int:
    total_sections = 0
    for (arxiv_id, version), (doc_json, _summaries) in db.docs.items():
        if not doc_json:
            continue
        total_sections += upload_chunks(
            arxiv_id=arxiv_id,
            version=version,
            doc_json=doc_json,
            dry_run=dry_run,
        )
    return total_sections


def backfill_postgres(
    db: PostgresDbClient,
    *,
    dry_run: bool,
    batch_size: int,
    offset: int,
    limit: Optional[int],
) -> int:
    total_sections = 0
    remaining = limit
    with db.Session() as session:
        while True:
            query = session.query(PaperVersionRow).order_by(
                PaperVersionRow.updated_at.desc()
            )
            if offset:
                query = query.offset(offset)
            query = query.limit(batch_size if remaining is None else min(batch_size, remaining))
            rows = query.all()
            if not rows:
                break

            for row in rows:
                doc_json = row.lumi_doc
                if not doc_json:
                    continue
                total_sections += upload_chunks(
                    arxiv_id=row.arxiv_id,
                    version=row.version,
                    doc_json=doc_json,
                    dry_run=dry_run,
                )

            if remaining is not None:
                remaining -= len(rows)
                if remaining <= 0:
                    break

            offset += len(rows)

    return total_sections


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill Lumi doc index + section chunks to storage"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Batch size for Postgres backfill",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Offset for Postgres backfill",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of docs to scan (Postgres only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many sections would be uploaded without saving",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(message)s")
    db = get_db_client()

    if isinstance(db, InMemoryDbClient):
        total_sections = backfill_in_memory(db, dry_run=args.dry_run)
    elif isinstance(db, PostgresDbClient):
        total_sections = backfill_postgres(
            db,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            offset=args.offset,
            limit=args.limit,
        )
    else:
        logger.error("Unsupported DB client: %s", type(db).__name__)
        return 1

    logger.info("Uploaded %d sections", total_sections)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
