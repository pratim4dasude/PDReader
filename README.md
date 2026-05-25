<h1 align="center">PDReader</h1>

<div align="center">

![React](https://img.shields.io/badge/React_18-20232A?style=flat&logo=react&logoColor=61DAFB)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat&logo=typescript&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL_16-4169E1?style=flat&logo=postgresql&logoColor=white)
![pgvector](https://img.shields.io/badge/pgvector-Vector%20Search-4169E1?style=flat&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-DC382D?style=flat&logo=redis&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=flat&logo=openai&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C?style=flat&logo=langchain&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white)

**A local-first PDF study assistant powered by hybrid RAG and an agentic chat pipeline**

*Upload your books, ask anything, get answers grounded in the actual text — with citations*

</div>

---

![PDReader](image.png)

---

## What it does

- Upload multiple PDFs through a React UI; ingestion runs in the background so large books never block the request
- Hybrid retrieval combines `pgvector` cosine similarity with PostgreSQL full-text search and reciprocal-rank fusion — exact terms like API names and acronyms aren't missed by embeddings alone
- Chat is routed through a LangGraph agent that classifies intent before doing anything; greetings stay cheap, book-grounded questions go through the full retrieval pipeline
- Per-document summaries and topic maps are generated at ingest time and reused for overview and study questions without touching retrieval again
- Answers surface collapsible source snippets linked back to the original page

---

## Architecture

```
  +---------------------------------------------------------------+
  |                          Browser                              |
  |          React + TypeScript  (Vite · Tailwind · Axios)        |
  |          upload  |  document list  |  chat  |  poll           |
  +--------+---------+----------------+---------+-----------------+
           |                                    |
     POST /upload                         POST /chat
           |                                    |
           v                                    v
  +--------+------------------------------------+----------------+
  |                        FastAPI                               |
  |      validate -> persist -> enqueue          run agent       |
  +--------+-----------------------------------------------------+
           |                          |
        enqueue                  hybrid query
           |                          |
           v                          v
  +--------+--------+    +-----------+-------------+
  |   Redis (RQ)    |    |  PostgreSQL + pgvector  |
  |  pdreader queue |    |  docs · chunks · jobs   |
  +--------+--------+    +-------------------------+
           |
        dequeue
           |
           v
  +--------+---------------------------+
  |          RQ Worker                 |
  |                                    |
  |   PyPDF extract + sanitize         |
  |            |                       |
  |   chunk  (500 tokens / 50 overlap) |
  |            |                       |
  |   embed  (text-embedding-3-small)  |
  |            |                       |
  |   persist pages + chunks + vectors |
  |            |                       |
  |   generate summary + topic map     |
  |            |                       |
  |   mark document  ready             |
  +------------------------------------+
           |
           v
  +--------+---------------------------+
  |           OpenAI API               |
  |   text-embedding-3-small · gpt-4o  |
  +------------------------------------+
```

### Chat pipeline

```
  query
    |
    v
  +-------------------+
  |  classify intent  |
  +--+------+------+--+
     |      |      |
     |      |      +---------------------------+
     |      |                                  |
  greeting  overview / study            code / search
  general       |                              |
     |    precomputed summary          hybrid retrieval
     |       + topic map              vector + FTS + RRF
     |          |                              |
     |          +----------+-------------------+
     |                     |
     |                     v
     |             +-------+-------+
     |             |   synthesize  |
     |             |   GPT-4o-mini |
     |             +-------+-------+
     |                     |
     +----------+----------+
                |
                v
       +------------------+
       |  citation guard  |
       |  flags answers   |
       |  with no source  |
       +--------+---------+
                |
                v
            Browser
```

---

## How it's built

This started as a basic RAG demo — upload PDF, embed chunks, query them. The problem was that approach breaks quickly on real books: large files time out on upload, exact terms get lost in embedding space, and every question hits retrieval even when it doesn't need to. These are the pieces that fix that.

**Redis + RQ — async ingestion**

Embedding a 400-page book takes time. Instead of doing that work inside the HTTP request (which would just time out), the upload endpoint saves the file, creates a job record, and puts the job on a Redis queue immediately. A separate RQ worker picks it up and processes it in the background. The frontend polls `/api/jobs/{id}` and shows progress at five checkpoints — 10% on start, 35% after chunking, 50% after summarising, 75% after embedding, 100% on completion. The API stays responsive regardless of book size.

**pgvector + full-text search + RRF — hybrid retrieval**

Pure vector search misses exact terms. If someone asks about `plainto_tsquery` or a specific chapter name, the embedding for that query might return conceptually related chunks rather than the ones that actually mention it. So retrieval runs two searches in parallel — semantic search via `pgvector` cosine distance, and keyword search via PostgreSQL `tsvector` / `ts_rank` (the `search_vector` column is precomputed at ingest time). The two ranked lists are then merged using reciprocal-rank fusion (`score = 1 / (rank + 60)`), which rewards chunks that appear in both lists. Everything stays inside Postgres — no separate vector database to manage.

**LangGraph agent — intent routing**

A single RAG call for every message is wasteful and often wrong. "What is this book about?" doesn't need retrieval — it needs the precomputed summary. "Hi" doesn't need anything. The agent classifies intent first using a deterministic regex/word-list matcher, then routes to the right node. Greetings get a canned reply. Overview and study questions read from the per-document summary and topic map generated at ingest time. Only code and search questions go through full hybrid retrieval. This keeps cost low and latency fast for most messages, and reserves the expensive path for questions that actually need it.

**Summaries and topic maps at ingest time**

When a document finishes processing, the worker makes one LLM call to generate a structured summary and topic map for the whole book and stores them on the document record. Overview and study intents read directly from those fields — no retrieval, no embedding lookup. If the fields are missing or stale, the overview node refreshes them on demand. This means the most common "what does this book cover" type questions are nearly instant.

**Citation guard**

When the agent routes a question through retrieval and synthesis but ends up with no source chunks attached to the answer, it's a sign the model may have generated something unsupported. The citation guard node catches this and appends a low-confidence disclaimer to the response rather than silently returning an ungrounded answer.

---

## Setup

Requires Python 3.11+, Node 18+, Docker Desktop, and an OpenAI API key.

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate        # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # add OPENAI_API_KEY
```

```bash
# Frontend
cd frontend && npm install
```

```bash
# Run everything
python -u start_dev.py
```

`start_dev.py` boots Postgres and Redis via Docker, runs Alembic migrations, then starts the API, RQ worker, and Vite dev server together. `Ctrl+C` stops the whole stack.

Frontend → `http://localhost:5173` &nbsp;|&nbsp; API → `http://localhost:8000`

---

## API

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/documents/upload` | Upload one or more PDFs (multipart) |
| `GET` | `/api/documents` | List documents with latest job status |
| `DELETE` | `/api/documents/{id}` | Delete a document and cascade |
| `GET` | `/api/jobs/{id}` | Poll ingestion progress |
| `POST` | `/api/chat` | Ask a question against selected documents |

**Request**
```json
{
  "query": "What skills do I need to understand these books?",
  "document_ids": ["document-uuid"]
}
```

**Response**
```json
{
  "answer": "Focus first on Python, ML basics, embeddings, retrieval...",
  "sources": [{ "filename": "AI_Engineering.pdf", "chunk_text": "...", "page": 12 }],
  "model": "gpt-4o-mini",
  "intent": "study",
  "used_tools": ["document_overview"]
}
```

---

<div align="center">
If you find this useful, a ⭐ star on the repo is always appreciated.
</div>
