"""
CLI helper to ingest new arXiv papers into the local arxiv-sanity-lite store.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.arxiv_sanity import ArxivSanityStore, DEFAULT_QUERY
from backend.config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Arxiv sanity-lite ingest")
    parser.add_argument(
        "-n",
        "--num",
        type=int,
        default=200,
        help="Up to how many papers to fetch",
    )
    parser.add_argument(
        "-s",
        "--start",
        type=int,
        default=0,
        help="Start at what index",
    )
    parser.add_argument(
        "-b",
        "--break-after",
        type=int,
        default=3,
        help="Stop after N empty updates (0 to disable)",
    )
    parser.add_argument(
        "-q",
        "--query",
        type=str,
        default=None,
        help="Override arXiv query string",
    )
    args = parser.parse_args()

    settings = get_settings()
    store = ArxivSanityStore(settings.arxiv_sanity_data_dir)
    query = args.query or settings.arxiv_sanity_query or DEFAULT_QUERY
    updated = store.ingest(
        query=query, num=args.num, start=args.start, break_after=args.break_after
    )
    return 0 if updated > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
