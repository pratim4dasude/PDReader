# PDReader

PDReader is a full-stack, local-first PDF study assistant. Users upload one or more PDF books; the system extracts pages, chunks the text, generates embeddings, stores everything in PostgreSQL with `pgvector`, and exposes a chat interface that routes each question through a LangGraph agent. Depending on intent, the agent answers from a document overview, a study-guidance flow, a code/practice flow, or a hybrid semantic + keyword retrieval pipeline grounded in the uploaded material.

The project began as a minimal PDF RAG demo and was hardened into a more production-shaped local system with durable storage, asynchronous ingestion, hybrid retrieval, worker observability, and an agentic chat flow.

---

![Alternative Text](image.png)

## Table of Contents

- [Capabilities](#capabilities)
- [Tech Stack](#tech-stack)
- [System Architecture](#system-architecture)
  - [High-Level Topology](#high-level-topology)
  - [Component Responsibilities](#component-responsibilities)
  - [Ingestion Pipeline](#ingestion-pipeline)
  - [Chat and Agent Pipeline](#chat-and-agent-pipeline)
  - [Retrieval Subsystem](#retrieval-subsystem)
  - [Data Model](#data-model)
  - [Runtime Topology](#runtime-topology)
- [API Reference](#api-reference)
- [Local Setup](#local-setup)
- [Run Everything](#run-everything)
- [Manual Run Commands](#manual-run-commands)
- [Project Structure](#project-structure)
- [Engineering Notes](#engineering-notes)
- [Known Limits](#known-limits)

---

## Capabilities

- Upload and manage multiple PDF documents through a single-page React interface.
- Ingest large books asynchronously through a Redis-backed RQ worker so HTTP requests never block on extraction or embedding.
- Persist pages, chunks, embeddings, document summaries, and topic maps in PostgreSQL.
- Serve hybrid retrieval combining `pgvector` cosine similarity with PostgreSQL full-text search and reciprocal-rank fusion.
- Route chat traffic through a LangGraph state machine that classifies intent and dispatches to specialised nodes (greeting, general chat, overview, study guidance, code/practice, document-grounded Q&A).
- Surface answer citations as collapsible source snippets in the UI.
- Emit structured logs across upload, ingestion, retrieval, and chat phases for local debugging.
- Boot the entire local stack (Postgres, Redis, migrations, API, worker, frontend) from a single Python launcher.

---

## Tech Stack

### Frontend

| Technology | Purpose |
| --- | --- |
| React 18 | Single-page UI |
| TypeScript | Typed frontend code |
| Vite | Dev server and build tooling |
| Tailwind CSS | Utility-first styling |
| Lucide React | Icon set |
| Axios | HTTP client |

### Backend

| Technology | Purpose |
| --- | --- |
| FastAPI | Async HTTP API |
| Pydantic | Request/response schemas |
| SQLAlchemy 2.x | ORM (typed `Mapped` models) |
| Alembic | Schema migrations |
| PostgreSQL 16 | Durable relational storage |
| pgvector | Vector similarity search inside Postgres |
| Redis 7 | Queue backend |
| RQ (`SimpleWorker`) | Background job runner (Windows-compatible) |
| LangChain | PDF loading, splitting, OpenAI integrations |
| LangGraph | Agent workflow and intent routing |
| OpenAI | Chat completion and embeddings |
| PyPDF | PDF text extraction via LangChain loader |
| `aiofiles` | Non-blocking upload writes |

### Infrastructure

| Technology | Purpose |
| --- | --- |
| Docker Compose | Local Postgres (`pgvector/pgvector:pg16`) and Redis |
| `start_dev.py` | Orchestrates Docker, Alembic, API, worker, and frontend |

---

## System Architecture

PDReader is built as four loosely coupled layers: a React client, a FastAPI control plane, an RQ-backed data plane for ingestion, and a Postgres + Redis storage tier. The control plane never performs heavy work synchronously; it only validates input, persists state, enqueues jobs, runs retrieval, and orchestrates the LangGraph agent.

### High-Level Topology

```text
+------------------------------------------------------------------+
|                            Browser                               |
|  React + TypeScript SPA (Vite, Tailwind, Axios)                  |
|  - Upload UI, document list, polling, chat, markdown rendering   |
+------------------------------+-----------------------------------+
                               | HTTP / JSON (Vite proxy -> :8000)
                               v
+------------------------------------------------------------------+
|                       FastAPI Control Plane                      |
|  main.py (routes) -> repositories.py (writes) -> agent.py (chat) |
|  - Validates uploads, persists rows, enqueues RQ jobs            |
|  - Runs LangGraph agent on /api/chat                             |
+------------+---------------------------------------+-------------+
             |                                       |
             | enqueue                               | hybrid query
             v                                       v
+-----------------------------+         +----------------------------+
|        Redis (RQ)           |         |   PostgreSQL + pgvector    |
|  pdreader queue             |         |  documents, pages, chunks, |
|                             |         |  jobs, chat_* tables       |
+-------------+---------------+         +-------------+--------------+
              |                                       ^
              | dequeue                               | read/write
              v                                       |
+------------------------------------------------------------------+
|                     RQ SimpleWorker (worker.py)                  |
|  tasks.process_document_job:                                     |
|  - PyPDF load + sanitize -> chunk -> embed -> persist            |
|  - LLM-generated summary + topic map                             |
|  - Job progress updates 10 -> 35 -> 50 -> 75 -> 100              |
+------------------------------+-----------------------------------+
                               |
                               v
+------------------------------------------------------------------+
|                          OpenAI API                              |
|  Embeddings (text-embedding-3-small) + Chat (gpt-4o-mini)        |
+------------------------------------------------------------------+
```

### Component Responsibilities

| Layer | File / Module | Responsibility |
| --- | --- | --- |
| API | `backend/main.py` | FastAPI app, CORS, route handlers, per-session in-memory chat history, request validation |
| Agent | `backend/agent.py` | LangGraph state machine; intent classifier; nodes for greeting, general, overview, retrieval, code, synthesis, citation guard |
| Services | `backend/services.py` | PDF loading and sanitisation, chunking, document overview extraction, OpenAI embedding + completion calls, summary/topic-map JSON generation |
| Retrieval | `backend/retrieval.py` | Semantic search (`pgvector` cosine), keyword search (`tsvector` + `plainto_tsquery`), reciprocal-rank fusion |
| Repositories | `backend/repositories.py` | All durable writes: document/job lifecycle, content replacement, sanitised metadata |
| Models | `backend/models.py` | SQLAlchemy ORM (`DocumentRecord`, `PageRecord`, `ChunkRecord`, `JobRecord`, `ChatSessionRecord`, `ChatMessageRecord`) |
| Schemas | `backend/schemas.py` | Pydantic DTOs and `DocumentStatus` enum |
| Tasks | `backend/tasks.py` | RQ job body: orchestrates ingestion, persists progress, surfaces failures |
| Worker | `backend/worker.py` | `SimpleWorker` entrypoint chosen for Windows compatibility |
| Queue | `backend/task_queue.py` | Single Redis connection and named `pdreader` queue |
| Infra | `backend/infrastructure.py` | Standalone Postgres/Redis healthchecks |
| Config | `backend/config.py` | Env-backed `Settings` (OpenAI, DB, Redis, embedding dimensions) |
| DB | `backend/db.py` | SQLAlchemy engine, `SessionLocal`, FastAPI `get_db` dependency |
| Migrations | `backend/alembic/` | Schema management; `pgvector` extension enabled in initial migration |
| Launcher | `start_dev.py` | Boots Docker services, runs migrations, starts API + worker + Vite |
| Frontend | `frontend/src/App.tsx` | Upload, polling, chat UI, lightweight markdown renderer, collapsible sources |
| Frontend API | `frontend/src/api.ts` | Axios client wrapping `/api` namespace |

### Ingestion Pipeline

The ingestion path is fully asynchronous from the caller's perspective. The HTTP request returns as soon as the file is persisted and a job is enqueued; the worker then drives the document to `ready` while the frontend polls.

```text
Client                FastAPI                Postgres            Redis/RQ              Worker                OpenAI
  |                     |                       |                   |                     |                     |
  |-- POST /upload ---->|                       |                   |                     |                     |
  |                     |-- write file (uploads/<uuid>_<name>)      |                     |                     |
  |                     |-- INSERT document(status=pending) ------->|                     |                     |
  |                     |-- INSERT job(status=queued, progress=0) ->|                     |                     |
  |                     |-- enqueue process_document_job ---------->|                     |                     |
  |                     |-- UPDATE job.rq_job_id ------------------>|                     |                     |
  |<-- 200 DocumentResponse[] (with current_job_id) ----------------|                     |                     |
  |                     |                       |                   |--- dequeue -------->|                     |
  |                     |                       |                   |                     |-- UPDATE job=processing, progress=10
  |                     |                       |                   |                     |-- load PDF (PyPDF), sanitize text
  |                     |                       |                   |                     |-- split into chunks (500/50)
  |                     |                       |                   |                     |-- UPDATE job.progress=35
  |                     |                       |                   |                     |-- summary + topic_map ---> ChatOpenAI
  |                     |                       |                   |                     |-- UPDATE job.progress=50
  |                     |                       |                   |                     |-- embed chunks ----------> OpenAIEmbeddings
  |                     |                       |                   |                     |-- replace pages + chunks + vectors
  |                     |                       |                   |                     |-- UPDATE job.progress=75
  |                     |                       |                   |                     |-- UPDATE document=ready, page_count, chunk_count, summary, topic_map
  |                     |                       |                   |                     |-- UPDATE job=completed, progress=100
  |-- GET /jobs/{id} -->|-- SELECT job -------------------------------------------------->|                     |
  |<-- progress --------|                       |                   |                     |                     |
```

Failure handling: any exception inside `process_document_job` triggers a rollback, then a best-effort write to `document.status='error'` and `job.status='failed'` with the exception message, and finally re-raises so RQ records the failure.

### Chat and Agent Pipeline

Chat requests are not blindly fed to retrieval. `agent.py` builds a LangGraph state machine that first classifies intent, then dispatches to the right node. This keeps cost low for greetings, lets overview/study questions use precomputed summaries, and reserves hybrid retrieval for questions that actually need book excerpts.

```text
                        +----------------+
                        |     route      |  classify_intent(query)
                        +-------+--------+
                                |
       +------------------------+-----------+--------+-----------+
       |            |           |           |        |           |
       v            v           v           v        v           v
   greeting     general     overview      study     code      retrieve
       |            |           |           |        |           |
       |            |           |           +---->-->+           |
       |            |           |                   (code wraps   |
       |            |           |                    retrieval +  |
       |            |           |                    overview)    |
       |            |           v                                 v
       |            |       synthesize <--------------------- synthesize
       |            |           |                                 |
       +--->--------+-->--------+---->-->-->---+-------<----------+
                                              |
                                              v
                                       citation_guard
                                              |
                                              v
                                             END
```

Intent classification (`classify_intent`) is a deterministic, regex/word-list matcher over a normalised query. It checks greeting tokens first, then help/general phrases, then code-with-document phrases, then overview, study, and finally a fallback that promotes any document- or technical-term-bearing query to `search`.

Per-node behaviour:

| Node | Role |
| --- | --- |
| `route` | Runs `classify_intent`, seeds empty `context/sources/used_tools` |
| `greeting` | Short canned reply; no retrieval |
| `general` | Canned non-document help reply; no retrieval |
| `overview` | Reads `document.summary` and `topic_map`; refreshes them via OpenAI if missing or stale; appends per-document context blocks and synthesised sources |
| `retrieve` | Calls `hybrid_search` and appends fused chunks to context with chunk-derived sources |
| `code` | Rewrites query with code intent, runs retrieval, then overview, restores original query for synthesis |
| `synthesize` | Calls `generate_answer` with intent-specific guidance for overview/study/code |
| `citation_guard` | Appends a low-confidence disclaimer when a document-grounded answer has no sources |

The FastAPI handler maintains an in-memory chat history keyed by the sorted set of selected `document_ids` and trims history to the last five turns inside the prompt.

### Retrieval Subsystem

Retrieval is hybrid by design because technical books rely heavily on exact terms (APIs, acronyms, chapter names, code identifiers) that pure embedding similarity often misses.

```text
                     query
                       |
       +---------------+----------------+
       |                                |
       v                                v
+----------------+               +----------------+
| semantic_search|               | keyword_search |
| OpenAI embed   |               | plainto_tsquery|
| pgvector       |               | ts_rank        |
| cosine_distance|               |                |
| limit=8        |               | limit=8        |
+-------+--------+               +--------+-------+
        |                                |
        +-------------+------------------+
                      v
              +-----------------+
              | fuse_results    |  reciprocal-rank fusion: 1 / (rank + 60)
              | dedup by        |  sum scores, mark overlap as "hybrid"
              | (doc_id, text)  |
              +--------+--------+
                       |
                       v
                  top-K chunks (final_k=8)
```

Implementation details:

- Semantic side: `ChunkRecord.embedding.cosine_distance(query_embedding)` ordered ascending, scored as `1 / (1 + distance)`.
- Keyword side: `to_tsvector` is precomputed into `ChunkRecord.search_vector` during ingestion; queries use `plainto_tsquery('english', q)` and rank with `ts_rank`.
- Fusion: classic RRF with `k=60`. Items appearing in both lists pick up additive score and are tagged `source='hybrid'`.
- The result set is constrained to the caller's `document_ids` on both sides, so cross-document leakage is impossible.

### Data Model

Defined in `backend/models.py` and migrated in `backend/alembic/versions/0001_initial_schema.py`.

```text
documents (id PK, filename, file_path, status, page_count, chunk_count, summary, topic_map JSONB, error_message, created_at, updated_at)
   |
   |---- pages       (id PK, document_id FK CASCADE, page_number, text)
   |
   |---- chunks      (id PK, document_id FK CASCADE, page_start, page_end,
   |                  chunk_index, chunk_type, text,
   |                  embedding VECTOR(1536), search_vector TSVECTOR,
   |                  extra_metadata JSONB)
   |
   +---- jobs        (id PK, document_id FK SET NULL, job_type, status,
                      progress, error_message, rq_job_id, attempts)

chat_sessions  (id PK, title)
   |
   +---- chat_messages (id PK, session_id FK CASCADE, role, content,
                        intent, citations JSONB)
```

Notes:

- `embedding` column dimension is driven by `EMBEDDING_DIMENSIONS` (default `1536`, matching `text-embedding-3-small`). Changing the model requires a new migration to alter the vector dimension.
- `search_vector` is populated on chunk insert and indexed for `@@` matches.
- `documents.status` is one of `pending | processing | ready | error` (`DocumentStatus` enum in `schemas.py`).
- `jobs.status` is `queued | processing | completed | failed`; `progress` advances monotonically through five checkpoints during ingestion.

### Runtime Topology

The default local topology runs everything on `127.0.0.1`:

| Service | Host | Port | Started By |
| --- | --- | --- | --- |
| Frontend (Vite) | 127.0.0.1 | 5173 | `npm run dev` |
| FastAPI | 127.0.0.1 | 8000 | `uvicorn main:app --reload` |
| RQ worker | local process | — | `python worker.py` |
| PostgreSQL | localhost | 5432 | Docker (`pdreader-postgres`) |
| Redis | localhost | 6379 | Docker (`pdreader-redis`) |

`start_dev.py` brings up Docker services, runs Alembic to head, then starts the API, worker, and Vite as child processes and tears them down on `Ctrl+C`. On Windows it uses `taskkill /T /F` to stop process trees cleanly.

---

## API Reference

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/`, `/health`, `/api/health` | Health check; reports OpenAI configuration |
| `POST` | `/api/documents/upload` | Upload one or more PDFs (multipart) |
| `GET` | `/api/documents` | List documents with latest job id |
| `GET` | `/api/documents/{doc_id}` | Get a single document |
| `DELETE` | `/api/documents/{doc_id}` | Delete a document (file + DB cascade) |
| `DELETE` | `/api/documents` | Delete all documents |
| `GET` | `/api/jobs/{job_id}` | Poll background job status and progress |
| `POST` | `/api/chat` | Ask a question against the selected documents |

Chat request:

```json
{
  "query": "What skills do I need to understand these books?",
  "document_ids": ["document-uuid"]
}
```

Chat response:

```json
{
  "answer": "Based on the uploaded books, focus first on Python, ML basics, embeddings, retrieval, evaluation, and deployment...",
  "sources": [
    {
      "document_id": "document-uuid",
      "filename": "AI_Engineering.pdf",
      "chunk_text": "The book covers adapting foundation models...",
      "page": 12
    }
  ],
  "model": "gpt-4o-mini",
  "intent": "study",
  "used_tools": ["document_overview"]
}
```

If `document_ids` is omitted, the server falls back to every document whose `status='ready'`.

---

## Local Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker Desktop
- OpenAI API key

### Backend environment

```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `backend/.env`:

```env
OPENAI_API_KEY=sk-your-key
OPENAI_CHAT_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
DATABASE_URL=postgresql+psycopg://pdreader:pdreader@localhost:5432/pdreader
REDIS_URL=redis://localhost:6379/0
```

### Frontend dependencies

```powershell
cd frontend
npm install
```

---

## Run Everything

From the project root:

```powershell
python -u start_dev.py
```

This starts:

- Postgres and Redis with Docker Compose.
- Alembic migrations against the live database.
- FastAPI backend on `http://127.0.0.1:8000`.
- RQ worker for PDF ingestion.
- React frontend on `http://127.0.0.1:5173`.

Press `Ctrl+C` in the same terminal to stop both the application processes and the Docker services.

---

## Manual Run Commands

If you want to run services separately:

```powershell
docker compose up -d
cd backend
.\venv\Scripts\alembic upgrade head
.\venv\Scripts\python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd backend
.\venv\Scripts\python worker.py
```

In another terminal:

```powershell
cd frontend
npm run dev
```

---

## Project Structure

```text
PDReader/
  backend/
    main.py              FastAPI routes and API wiring
    agent.py             LangGraph assistant workflow and intent routing
    services.py          PDF processing, summaries, embeddings, answer generation
    retrieval.py         Hybrid semantic + keyword retrieval and RRF fusion
    repositories.py      Database write/update helpers
    models.py            SQLAlchemy ORM models
    schemas.py           Pydantic API schemas and enums
    tasks.py             RQ document processing job
    worker.py            Windows-compatible RQ SimpleWorker entrypoint
    task_queue.py        Redis connection and named RQ queue
    db.py                SQLAlchemy engine and session factory
    config.py            Env-backed Settings object
    infrastructure.py    Standalone Postgres/Redis healthchecks
    alembic/             Database migrations (initial schema enables pgvector)
    uploads/             Local PDF storage
    vectorstores/        Legacy local vectorstore directory
  frontend/
    src/App.tsx          React UI (upload, polling, chat, markdown renderer)
    src/api.ts           Axios API client
    src/types.ts         Frontend types matching backend schemas
  docker-compose.yml     Local Postgres (pgvector) + Redis
  start_dev.py           One-command local launcher
  alembic.ini            Alembic configuration
```

---

## Engineering Notes

- Replaced fragile in-memory and local-JSON behaviour with a durable Postgres-backed model.
- Added `pgvector`-backed semantic search alongside PostgreSQL full-text search and RRF fusion.
- Moved heavy ingestion off the request path with Redis/RQ so large books no longer cause HTTP timeouts.
- Modelled job lifecycle with explicit `pending | processing | ready | error` document states and `queued | processing | completed | failed` job states, surfaced in the UI via polling.
- Added structured logs across upload, processing, retrieval, and chat decisions for local debugging.
- Used RQ `SimpleWorker` to stay compatible with Windows (no `fork()`).
- Hardened Windows file path handling for uploads.
- Sanitised extracted PDF text (null bytes, control characters) before persistence to avoid PostgreSQL text errors.
- Generated per-document summaries and topic maps at ingest time so overview and study intents do not require retrieval.
- Routed chat through an explicit LangGraph state machine instead of a single RAG call, keeping cheap intents cheap and grounded intents grounded.
- Added a citation guard so any document-grounded answer that ends up without sources is flagged as low-confidence.
- Shipped a single-command launcher (`start_dev.py`) that boots Docker, runs migrations, and supervises the stack.

---

## Known Limits

- Embeddings and answer generation depend on OpenAI; offline operation is not supported out of the box.
- PDF extraction quality is bounded by the source PDF text layer; scanned PDFs without OCR will degrade gracefully but produce sparse retrieval.
- Chat history is held in process memory keyed by the selected document set and resets on backend restart; the `chat_sessions` / `chat_messages` tables exist but are not yet wired into the chat endpoint.
- Retrieval can still be improved with reranking, query rewriting, and an automated evaluation harness.
- Changing the embedding model requires a new Alembic migration to adjust the `vector` column dimension.
