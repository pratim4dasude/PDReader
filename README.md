# PDReader

PDReader is a full-stack PDF study assistant. It lets users upload one or more PDF books, processes them in the background, stores searchable chunks in Postgres with pgvector, and provides a chat interface that can answer questions, summarize documents, suggest reading plans, explain required skills, and provide original practice/code examples from the uploaded material.

The project started as a simple PDF RAG app and was upgraded into a more production-like local system with durable storage, async processing, hybrid retrieval, worker diagnostics, and an agentic chat flow.

## What It Does

- Upload and manage multiple PDF documents.
- Process large books asynchronously through a Redis/RQ worker.
- Extract pages, chunks, embeddings, summaries, and topic maps.
- Store document metadata, pages, chunks, vectors, and jobs in Postgres.
- Use pgvector semantic search plus PostgreSQL full-text keyword search.
- Route chat requests through a LangGraph assistant flow.
- Support normal chat, greetings, document overview, study guidance, code/practice ideas, and document-grounded Q&A.
- Show source snippets in a collapsible UI section.
- Log processing and chat decisions in the backend terminal for debugging.
- Start the full local stack with one Python launcher.

## Tech Stack

### Frontend

| Technology | Purpose |
| --- | --- |
| React | Web UI |
| TypeScript | Typed frontend code |
| Vite | Local dev server and build tooling |
| Tailwind CSS | Utility-first styling |
| Lucide React | UI icons |
| Axios | API client |

### Backend

| Technology | Purpose |
| --- | --- |
| FastAPI | HTTP API |
| SQLAlchemy | Database ORM |
| Alembic | Database migrations |
| PostgreSQL | Durable relational storage |
| pgvector | Vector similarity search inside Postgres |
| Redis | Queue backend |
| RQ | Background job worker |
| LangChain | PDF loading, splitting, OpenAI integrations |
| LangGraph | Assistant workflow routing |
| OpenAI | Chat model and embedding model |
| PyPDF | PDF text extraction through LangChain loader |

### Infrastructure

| Technology | Purpose |
| --- | --- |
| Docker Compose | Runs local Postgres and Redis |
| `start_dev.py` | Starts Docker services, migrations, backend, worker, and frontend together |

## Architecture

```text
Browser UI
  |
  | HTTP
  v
FastAPI backend
  |
  | upload PDFs
  v
Local upload storage
  |
  | enqueue processing job
  v
Redis + RQ worker
  |
  | extract pages, chunks, embeddings, summaries
  v
Postgres + pgvector
  |
  | chat query
  v
LangGraph study assistant
  |
  | intent routing
  | - greeting/general chat
  | - document overview
  | - study guidance
  | - code/practice examples
  | - hybrid retrieval Q&A
  v
OpenAI chat model
  |
  v
Answer + source snippets
```

## Processing Flow

1. User uploads one or more PDFs from the React app.
2. FastAPI saves each file under `backend/uploads`.
3. A `documents` row and a `jobs` row are created in Postgres.
4. The processing task is queued in Redis.
5. The RQ worker loads the PDF, sanitizes extracted text, stores pages, chunks, and embeddings, and updates progress.
6. The worker generates a document summary and topic map for overview/study questions.
7. The frontend polls document/job status until the document is ready.

This design avoids long API requests timing out when a large book is uploaded.

## Chat Flow

The chat system does not send every message directly into retrieval. It first classifies the request:

- `greeting`: short natural response.
- `general`: normal non-document chat.
- `overview`: document summaries and topic maps.
- `study`: reading plan, prerequisite skills, what to learn, and what to focus on.
- `code`: original practice/code examples based on book concepts.
- `search`: hybrid retrieval over document chunks.

For document-grounded answers, the backend returns sources separately. The frontend renders the answer as formatted Markdown-like text and keeps sources inside a collapsible `Sources` section.

## Retrieval

PDReader uses hybrid retrieval:

- Semantic retrieval with OpenAI embeddings stored in pgvector.
- Keyword retrieval with PostgreSQL full-text search.
- Reciprocal-rank-style fusion to combine both result sets.

This is better than vector-only retrieval for technical books because exact terms, acronyms, chapter names, and code-related words often matter.

## API Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/health` | Health check |
| `GET` | `/api/health` | Health check |
| `POST` | `/api/documents/upload` | Upload one or more PDFs |
| `GET` | `/api/documents` | List uploaded documents |
| `GET` | `/api/documents/{doc_id}` | Get one document |
| `DELETE` | `/api/documents/{doc_id}` | Delete one document |
| `DELETE` | `/api/documents` | Delete all documents |
| `GET` | `/api/jobs/{job_id}` | Check background job status |
| `POST` | `/api/chat` | Ask a chat question |

Example chat request:

```json
{
  "query": "What skills do I need to understand these books?",
  "document_ids": ["document-uuid"]
}
```

Example chat response:

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

Edit `backend/.env` and add:

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

## Run Everything

From the project root:

```powershell
python -u start_dev.py
```

This starts:

- Postgres and Redis with Docker Compose.
- Alembic migrations.
- FastAPI backend on `http://127.0.0.1:8000`.
- RQ worker for PDF processing.
- React frontend on `http://127.0.0.1:5173`.

Press `Ctrl+C` in the same terminal to stop the app services and Docker services.

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

## Project Structure

```text
PDReader/
  backend/
    main.py              FastAPI routes and API wiring
    agent.py             LangGraph assistant workflow and intent routing
    services.py          PDF processing, summaries, embeddings, answer generation
    retrieval.py         Hybrid semantic + keyword retrieval
    repositories.py      Database write/update helpers
    models.py            SQLAlchemy database models
    schemas.py           Pydantic API schemas
    tasks.py             RQ document processing job
    worker.py            Windows-compatible RQ worker entrypoint
    alembic/             Database migrations
  frontend/
    src/App.tsx          React UI
    src/api.ts           API client
    src/types.ts         Frontend types
  docker-compose.yml     Local Postgres + Redis
  start_dev.py           One-command local launcher
```

## Reviewer Notes

Important engineering work completed:

- Replaced fragile in-memory/local JSON behavior with durable Postgres models.
- Added pgvector-backed semantic search and PostgreSQL full-text search.
- Added Redis/RQ background processing so large PDFs do not block HTTP requests.
- Added job tracking and frontend polling for pending, processing, ready, and error states.
- Added backend logs for upload, processing, retrieval, and chat decisions.
- Added a Windows-compatible worker using RQ `SimpleWorker`.
- Fixed Windows path issues for uploaded files.
- Sanitized extracted PDF text to prevent PostgreSQL text errors.
- Added document summaries and topic maps for better overview/study answers.
- Added agent-style routing for normal chat vs document-grounded questions.
- Improved frontend formatting and collapsible source display.
- Added `start_dev.py` to run the whole stack from one command.

## Known Limits

- The app depends on OpenAI for embeddings and answer generation.
- PDF extraction quality depends on the source PDF text layer.
- Chat history is currently kept in backend memory per document set, so it resets when the backend restarts.
- Retrieval quality can still be improved with reranking, query rewriting, and automated evaluation.
