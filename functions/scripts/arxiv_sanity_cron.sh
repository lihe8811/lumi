#!/bin/sh
set -e

if [ -f /app/.env ]; then
  set -a
  . /app/.env
  set +a
fi

cd /app
python3 scripts/arxiv_sanity_daemon.py --once
