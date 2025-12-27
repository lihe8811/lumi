"""
Daemon that periodically ingests new arXiv papers into the sanity store.
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.arxiv_sanity import ArxivSanityStore, DEFAULT_QUERY
from backend.config import get_settings

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Arxiv sanity-lite daemon")
    parser.add_argument(
        "-n",
        "--num",
        type=int,
        default=200,
        help="Up to how many papers to fetch per loop",
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
        help="Stop ingest after N empty updates (0 to disable)",
    )
    parser.add_argument(
        "-q",
        "--query",
        type=str,
        default=None,
        help="Override arXiv query string",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=1800,
        help="Seconds between ingest runs",
    )
    parser.add_argument(
        "--jitter-seconds",
        type=int,
        default=120,
        help="Max random jitter added to sleep",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single ingest and exit",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s %(levelname)s %(asctime)s %(message)s",
        datefmt="%m/%d/%Y %I:%M:%S %p",
    )

    settings = get_settings()
    store = ArxivSanityStore(settings.arxiv_sanity_data_dir)
    query = args.query or settings.arxiv_sanity_query or DEFAULT_QUERY

    while True:
        try:
            updated = store.ingest(
                query=query,
                num=args.num,
                start=args.start,
                break_after=args.break_after,
            )
            logger.info("Ingest complete, updated %d papers", updated)
        except Exception as exc:
            logger.exception("Ingest failed: %s", exc)

        if args.once:
            return 0

        sleep_for = args.interval_seconds + random.uniform(0, args.jitter_seconds)
        logger.info("Sleeping for %.1fs", sleep_for)
        time.sleep(sleep_for)


if __name__ == "__main__":
    raise SystemExit(main())
