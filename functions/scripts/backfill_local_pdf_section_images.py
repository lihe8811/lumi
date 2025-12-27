"""
Backfill local PDF image mapping to skip images before the Abstract page.

This re-extracts embedded PDF images for local-upload papers, mapping them only
to section images (skipping abstract), and overwrites storage at the existing
image paths.
"""

from __future__ import annotations

import argparse
import logging
import sys
import re
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.dependencies import get_db_client, get_storage_client
from backend.db import InMemoryDbClient, PostgresDbClient, PaperVersionRow
from backend.storage import InMemoryStorageClient
from backend.doc_chunks import build_doc_index, iter_section_chunks
from import_pipeline import image_utils
from import_pipeline import import_pipeline as pipeline

logger = logging.getLogger(__name__)

LOCAL_ID_PATTERN = re.compile(r"^\d{4}\.L\d{4}$")


def _is_local_id(arxiv_id: str) -> bool:
    return arxiv_id.startswith("local-") or bool(LOCAL_ID_PATTERN.match(arxiv_id))


def _get_dict_value(data: dict, *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


class DictImageContent:
    def __init__(self, data: dict):
        self._data = data

    @property
    def storage_path(self) -> str:
        return _get_dict_value(self._data, "storagePath", "storage_path") or ""

    @storage_path.setter
    def storage_path(self, value: str) -> None:
        if "storage_path" in self._data:
            self._data["storage_path"] = value
        else:
            self._data["storagePath"] = value

    @property
    def width(self) -> float:
        return _get_dict_value(self._data, "width") or 0.0

    @width.setter
    def width(self, value: float) -> None:
        self._data["width"] = value

    @property
    def height(self) -> float:
        return _get_dict_value(self._data, "height") or 0.0

    @height.setter
    def height(self, value: float) -> None:
        self._data["height"] = value


def collect_section_image_contents(doc_json: dict) -> list[DictImageContent]:
    results: list[DictImageContent] = []

    def scan_contents(contents: list[dict]) -> None:
        for content in contents:
            image_content = _get_dict_value(
                content, "imageContent", "image_content"
            )
            if isinstance(image_content, dict):
                results.append(DictImageContent(image_content))
            figure_content = _get_dict_value(
                content, "figureContent", "figure_content"
            ) or {}
            for image in _get_dict_value(figure_content, "images") or []:
                if isinstance(image, dict):
                    results.append(DictImageContent(image))

    def scan_sections(sections: list[dict]) -> None:
        for section in sections:
            scan_contents(_get_dict_value(section, "contents") or [])
            sub_sections = _get_dict_value(section, "subSections", "sub_sections") or []
            if sub_sections:
                scan_sections(sub_sections)

    scan_sections(doc_json.get("sections") or [])
    return results


def update_featured_image(doc_json: dict, image_path: str) -> None:
    metadata = doc_json.get("metadata") or {}
    metadata["featuredImage"] = {"imageStoragePath": image_path}
    doc_json["metadata"] = metadata


def pick_first_image_path(image_contents: list[DictImageContent]) -> str:
    for content in image_contents:
        if content.storage_path:
            return content.storage_path
    return ""


def backfill_doc(
    *,
    arxiv_id: str,
    version: str,
    doc_json: dict,
    summaries_json: dict,
    storage_pdf_path: str,
    db: InMemoryDbClient | PostgresDbClient,
    storage,
    dry_run: bool,
    skip_images: int,
    verbose: bool,
) -> int:
    try:
        pdf_bytes = storage.get_bytes(storage_pdf_path)
    except Exception as exc:
        if verbose:
            logger.warning(
                "Failed to fetch PDF for %s at %s: %s",
                arxiv_id,
                storage_pdf_path,
                exc,
            )
        return 0

    image_contents = collect_section_image_contents(doc_json)
    if not image_contents:
        if verbose:
            logger.info("No section images found for %s", arxiv_id)
        return 0

    headings = []
    for section in doc_json.get("sections") or []:
        heading = _get_dict_value(section, "heading") or {}
        text = _get_dict_value(heading, "text")
        if text:
            headings.append(text)
    abstract_page_index = image_utils.find_start_page_index(
        pdf_bytes, headings=headings
    )
    run_locally = isinstance(storage, InMemoryStorageClient)
    if dry_run:
        return len(image_contents)

    extracted_images = image_utils.extract_images_from_pdf_xobjects(
        pdf_bytes,
        image_contents=image_contents,
        run_locally=run_locally,
        storage_client=storage,
        start_page=abstract_page_index,
        skip_images=skip_images,
    )
    if extracted_images:
        image_path = pipeline._pick_featured_image(extracted_images, image_contents)
        if image_path:
            update_featured_image(doc_json, image_path)
        if verbose:
            logger.info(
                "Remapped %s: extracted %d images, featured %s",
                arxiv_id,
                len(extracted_images),
                image_path,
            )
    else:
        image_path = pick_first_image_path(image_contents)
        if image_path:
            update_featured_image(doc_json, image_path)
        if verbose:
            logger.info(
                "Remapped %s: no extracted images; featured %s",
                arxiv_id,
                image_path,
            )

    db.save_lumi_doc(arxiv_id, version, doc_json, summaries_json)

    base_path = f"papers/{arxiv_id}/v{version}"
    storage.upload_json(f"{base_path}/lumi_doc.json", doc_json)
    doc_index = build_doc_index(doc_json)
    storage.upload_json(f"{base_path}/lumi_doc_index.json", doc_index)
    for section in iter_section_chunks(doc_json):
        section_id = section.get("id")
        if not section_id:
            continue
        storage.upload_json(f"{base_path}/sections/{section_id}.json", section)

    return len(extracted_images)


def backfill_in_memory(
    db: InMemoryDbClient,
    *,
    dry_run: bool,
    skip_images: int,
    paper_id: Optional[str],
    verbose: bool,
) -> int:
    updated = 0
    storage = get_storage_client()
    for (arxiv_id, version), (doc_json, summaries_json) in db.docs.items():
        if paper_id and arxiv_id != paper_id:
            continue
        if not _is_local_id(arxiv_id):
            continue
        metadata = db.get_metadata(arxiv_id) or {}
        storage_pdf_path = metadata.get("storage_pdf_path")
        if not storage_pdf_path:
            storage_pdf_path = f"papers/{arxiv_id}/v{version}/source.pdf"
            if verbose:
                logger.info(
                    "Missing storage_pdf_path for %s; falling back to %s",
                    arxiv_id,
                    storage_pdf_path,
                )
        updated += backfill_doc(
            arxiv_id=arxiv_id,
            version=version,
            doc_json=doc_json,
            summaries_json=summaries_json,
            storage_pdf_path=storage_pdf_path,
            db=db,
            storage=storage,
            dry_run=dry_run,
            skip_images=skip_images,
            verbose=verbose,
        )
    return updated


def backfill_postgres(
    db: PostgresDbClient,
    *,
    dry_run: bool,
    batch_size: int,
    offset: int,
    limit: Optional[int],
    skip_images: int,
    paper_id: Optional[str],
    verbose: bool,
) -> int:
    updated = 0
    storage = get_storage_client()
    remaining = limit
    with db.Session() as session:
        while True:
            query = session.query(PaperVersionRow).order_by(
                PaperVersionRow.updated_at.desc()
            )
            if paper_id:
                query = query.filter(PaperVersionRow.arxiv_id == paper_id)
            if offset:
                query = query.offset(offset)
            query = query.limit(batch_size if remaining is None else min(batch_size, remaining))
            rows = query.all()
            if not rows:
                break

            for row in rows:
                if not _is_local_id(row.arxiv_id):
                    continue
                metadata = db.get_metadata(row.arxiv_id) or {}
                storage_pdf_path = metadata.get("storage_pdf_path")
                if not storage_pdf_path:
                    storage_pdf_path = (
                        f"papers/{row.arxiv_id}/v{row.version}/source.pdf"
                    )
                    if verbose:
                        logger.info(
                            "Missing storage_pdf_path for %s; falling back to %s",
                            row.arxiv_id,
                            storage_pdf_path,
                        )
                updated += backfill_doc(
                    arxiv_id=row.arxiv_id,
                    version=row.version,
                    doc_json=row.lumi_doc,
                    summaries_json=row.summaries,
                    storage_pdf_path=storage_pdf_path,
                    db=db,
                    storage=storage,
                    dry_run=dry_run,
                    skip_images=skip_images,
                    verbose=verbose,
                )

            if remaining is not None:
                remaining -= len(rows)
                if remaining <= 0:
                    break

            offset += len(rows)

    return updated


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill local PDF image mapping (skip pre-abstract images)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
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
        help="Report how many images would be processed without saving",
    )
    parser.add_argument(
        "--skip-images",
        type=int,
        default=0,
        help="Skip this many PDF images before mapping to section images",
    )
    parser.add_argument(
        "--paper-id",
        type=str,
        default=None,
        help="Only backfill a single paper id",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Log details about skipped papers",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(message)s")
    db = get_db_client()

    if isinstance(db, InMemoryDbClient):
        updated = backfill_in_memory(
            db,
            dry_run=args.dry_run,
            skip_images=args.skip_images,
            paper_id=args.paper_id,
            verbose=args.verbose,
        )
    elif isinstance(db, PostgresDbClient):
        updated = backfill_postgres(
            db,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            offset=args.offset,
            limit=args.limit,
            skip_images=args.skip_images,
            paper_id=args.paper_id,
            verbose=args.verbose,
        )
    else:
        logger.error("Unsupported DB client: %s", type(db).__name__)
        return 1

    logger.info("Processed %d images", updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
