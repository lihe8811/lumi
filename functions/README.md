# Lumi Backend (FastAPI)

This directory hosts the backend for Lumi, now targeting deployment on an Ubuntu server with Caddy, FastAPI, PostgreSQL, and Tencent COS (S3-compatible) storage. The legacy Firebase Functions flow is being refactored into HTTP APIs and a worker model.

## Prerequisites
- Python 3.11 (recommended)
- Optional but expected for production: PostgreSQL (TencentDB) and Tencent COS credentials

## Environment variables (`functions/.env`)
- `API_PREFIX=/api`
- `DATABASE_URL=postgresql://lumi_user:change_me_password@db-host:5432/lumi`
- `COS_BUCKET=your-cos-bucket-name`
- `COS_REGION=ap-region`
- `COS_ENDPOINT=https://cos.ap-region.myqcloud.com`
- `AWS_ACCESS_KEY_ID=your-cos-access-key`
- `AWS_SECRET_ACCESS_KEY=your-cos-secret-key`
- `GEMINI_API_KEY=your-gemini-key`
- `LUMI_USE_IN_MEMORY_BACKENDS=false`
- Optional queue settings: `REDIS_URL=redis://localhost:6379/0`

Set `LUMI_USE_IN_MEMORY_BACKENDS=true` to run locally without Postgres/COS.

## Install and run the API
```bash
cd functions
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start API on :8000
uvicorn backend.app:app --reload --port 8000
```

### Worker with Redis queue
- Start Redis locally (`brew services start redis`) or provide `REDIS_URL=redis://...`.
- Run the worker loop:
```bash
cd functions
source venv/bin/activate
python -m backend.worker
```

## Quick checks
- `POST /api/request_arxiv_doc_import` with `{"arxiv_id":"1234.56789","version":"1"}` → job id.
- `GET /api/job-status/{job_id}` → status (`WAITING` in the in-memory stub).
- `GET /api/sign-url?path=test/foo.png` → presigned URL stub (uses configured storage backend).

## Tests
```bash
cd functions
python -m unittest discover backend/tests
```

## Notes on refactor
- Storage is abstracted for Tencent COS (S3) with an in-memory fallback; GCS compatibility remains for legacy flows.
- Database is abstracted; a real `PostgresDbClient` still needs to be implemented (SQLAlchemy models/migrations). In-memory DB supports tests and local runs.
- The import/summarization pipeline should run in a worker process/queue that updates job status via the DB and writes artifacts to COS.

## Deploying on Ubuntu with Caddy (sketch)
1) Run API via systemd: `uvicorn backend.app:app --host 127.0.0.1 --port 8000` with `.env` loaded.  
2) Frontend: build in `frontend/` (`npm run build:prod`) and serve `/var/www/lumi` via Caddy.  
3) Sample Caddyfile:
```
lumi.example.com {
  root * /var/www/lumi
  file_server
  try_files {path} /index.html
  reverse_proxy /api/* 127.0.0.1:8000
  encode zstd gzip
  header Cache-Control "public, max-age=31536000, immutable" {
    path *.js *.css *.png *.svg
  }
  tls you@example.com
}
```

## Frontend (pointer)
See `frontend/` for the SPA. During API refactor, the frontend will be moved from Firebase callables to HTTP fetches against `/api/*` and will fetch presigned COS URLs for assets.
