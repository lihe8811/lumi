# Lumi

Lumi is a research prototype for reading and exploring academic papers with AI-powered summaries, concepts, and interactive views. This repository contains a FastAPI backend, a worker for import/summarization jobs, and a Lit-based frontend.

## Installation

### Prerequisites
- Python 3.11
- Node/Bun (frontend uses Bun)
- Redis and PostgreSQL (recommended for production; optional for local testing)

### Docker (recommended)
1) Create the env file for the backend:
```bash
cp functions/.env.example functions/.env
```
2) Start the stack:
```bash
docker compose up --build
```
3) Open the app:
- Frontend: `http://localhost:4201`
- Backend: `http://localhost:4000`

### Backend
```bash
cd functions
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env

# Start API (defaults to port 4000)
uvicorn backend.app:app --reload --port 4000
```

Start the worker in a separate terminal:
```bash
cd functions
source venv/bin/activate
python -m backend.worker
```

### Frontend
```bash
cd frontend
bun install
bun run serve
```

The frontend expects the backend on `http://localhost:4000`.

### Local-only mode
Set `LUMI_USE_IN_MEMORY_BACKENDS=true` in `functions/.env` to run without Postgres, Redis, or COS. This is useful for quick UI testing.

## License and Disclaimer
All software is licensed under the Apache License, Version 2.0 (Apache 2.0). You may not use this file except in compliance with the Apache 2.0 license. You may obtain a copy of the Apache 2.0 license at: https://www.apache.org/licenses/LICENSE-2.0.

Unless required by applicable law or agreed to in writing, all software and materials distributed here under the Apache 2.0 licenses are distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the licenses for the specific language governing permissions and limitations under those licenses.

Lumi is a research project under active development by a small team. If you have suggestions or feedback, feel free to submit an issue.
