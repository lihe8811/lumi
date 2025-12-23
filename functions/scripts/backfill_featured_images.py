"""
Backfill featured images for existing Lumi docs.

This scans stored Lumi docs for the first image/figure and writes it into
metadata.featuredImage.imageStoragePath so the gallery can use it as a cover.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.dependencies import get_db_client
from backend.db import InMemoryDbClient, PostgresDbClient, PaperVersionRow


logger = logging.getLogger(__name__)


def _get_dict_value(data: dict, *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def find_first_image_path(doc_json: dict) -> Optional[str]:
    def scan_content(content: dict) -> Optional[str]:
        image_content = _get_dict_value(content, "imageContent", "image_content") or {}
        image_path = _get_dict_value(image_content, "storagePath", "storage_path")
        if image_path:
            return image_path

        figure_content = _get_dict_value(content, "figureContent", "figure_content") or {}
        for image in _get_dict_value(figure_content, "images") or []:
            image_path = _get_dict_value(image, "storagePath", "storage_path")
            if image_path:
                return image_path
        return None

    def scan_section(section: dict) -> Optional[str]:
        for content in _get_dict_value(section, "contents") or []:
            image_path = scan_content(content)
            if image_path:
                return image_path

        for subsection in _get_dict_value(section, "subSections", "sub_sections") or []:
            image_path = scan_section(subsection)
            if image_path:
                return image_path
        return None

    abstract = doc_json.get("abstract") or {}
    for content in _get_dict_value(abstract, "contents") or []:
        image_path = scan_content(content)
        if image_path:
            return image_path

    for section in _get_dict_value(doc_json, "sections") or []:
        image_path = scan_section(section)
        if image_path:
            return image_path

    return None


def update_doc_featured_image(
    doc_json: dict, image_path: str, *, force: bool
) -> bool:
    metadata = doc_json.get("metadata") or {}
    existing = metadata.get("featuredImage") or {}
    if existing.get("imageStoragePath") and not force:
        return False

    metadata["featuredImage"] = {"imageStoragePath": image_path}
    doc_json["metadata"] = metadata
    return True


def backfill_in_memory(db: InMemoryDbClient, *, dry_run: bool, force: bool) -> int:
    updated = 0
    for (arxiv_id, version), (doc_json, summaries_json) in db.docs.items():
        image_path = find_first_image_path(doc_json)
        if not image_path:
            continue
        if update_doc_featured_image(doc_json, image_path, force=force):
            updated += 1
            if not dry_run:
                db.save_lumi_doc(arxiv_id, version, doc_json, summaries_json)
    return updated


def backfill_postgres(
    db: PostgresDbClient,
    *,
    dry_run: bool,
    force: bool,
    batch_size: int,
    offset: int,
    limit: Optional[int],
) -> int:
    updated = 0
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
                image_path = find_first_image_path(doc_json)
                if not image_path:
                    continue
                if update_doc_featured_image(doc_json, image_path, force=force):
                    updated += 1
                    if not dry_run:
                        row.lumi_doc = doc_json

            if not dry_run:
                session.commit()

            if remaining is not None:
                remaining -= len(rows)
                if remaining <= 0:
                    break

            offset += len(rows)

    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill featured images")
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
        "--force",
        action="store_true",
        help="Overwrite existing featuredImage values",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many docs would be updated without saving",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(message)s")
    db = get_db_client()

    if isinstance(db, InMemoryDbClient):
        updated = backfill_in_memory(db, dry_run=args.dry_run, force=args.force)
    elif isinstance(db, PostgresDbClient):
        updated = backfill_postgres(
            db,
            dry_run=args.dry_run,
            force=args.force,
            batch_size=args.batch_size,
            offset=args.offset,
            limit=args.limit,
        )
    else:
        logger.error("Unsupported DB client: %s", type(db).__name__)
        return 1

    logger.info("Updated %d docs", updated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
