import logging
import os
import uuid
from typing import Dict, List, Tuple

import aiofiles
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc
from sqlalchemy.orm import Session

from db import get_db
from models import DocumentRecord, JobRecord
from repositories import create_document, create_job, update_job
from agent import run_study_agent
from schemas import (
    ChatRequest,
    ChatResponse,
    DocumentResponse,
    DocumentStatus,
    HealthResponse,
    JobResponse,
    SourceDocument,
)
from services import OPENAI_MODEL, UPLOAD_DIR, delete_vectorstore
from task_queue import document_queue
from tasks import process_document_job

# ============ Logging ============

pdreader_logger = logging.getLogger("pdreader")
if not pdreader_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    )
    pdreader_logger.addHandler(handler)
pdreader_logger.setLevel(logging.INFO)
pdreader_logger.propagate = False

logger = logging.getLogger("pdreader.api")

# ============ App Setup ============

app = FastAPI(title="PDReader API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ Chat History ============

chat_histories: Dict[str, List[Tuple[str, str]]] = {}


def document_to_response(
    document: DocumentRecord,
    current_job_id: str | None = None,
) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        created_at=document.created_at,
        page_count=document.page_count,
        chunk_count=document.chunk_count,
        error_message=document.error_message,
        current_job_id=current_job_id,
    )


def job_to_response(job: JobRecord) -> JobResponse:
    return JobResponse(
        id=job.id,
        document_id=job.document_id,
        job_type=job.job_type,
        status=job.status,
        progress=job.progress,
        error_message=job.error_message,
        rq_job_id=job.rq_job_id,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


# ============ Routes ============


@app.get("/", response_model=HealthResponse)
@app.get("/health", response_model=HealthResponse)
@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    api_key = os.getenv("OPENAI_API_KEY", "")
    return HealthResponse(
        status="healthy",
        version="2.0.0",
        openai_configured=bool(api_key and api_key != "your_openai_api_key_here"),
    )


@app.post("/api/documents/upload", response_model=List[DocumentResponse])
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    del background_tasks

    results = []
    for file in files:
        if not file.filename.lower().endswith(".pdf"):
            logger.warning("Rejected non-PDF upload: filename=%s", file.filename)
            raise HTTPException(status_code=400, detail="Only PDF files supported")

        doc_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        filename = f"{doc_id}_{file.filename}"
        file_path = os.path.join(UPLOAD_DIR, filename)
        logger.info("Upload received: filename=%s doc_id=%s job_id=%s", file.filename, doc_id, job_id)

        async with aiofiles.open(file_path, "wb") as out_file:
            file_bytes = await file.read()
            await out_file.write(file_bytes)

        document = create_document(
            db,
            doc_id=doc_id,
            filename=file.filename,
            file_path=file_path,
            status=DocumentStatus.PENDING.value,
        )
        create_job(
            db,
            job_id=job_id,
            document_id=doc_id,
            job_type="process_document",
            status="queued",
            progress=0,
        )

        rq_job = document_queue.enqueue(
            process_document_job,
            job_id,
            doc_id,
            file_path,
            file.filename,
            job_timeout="2h",
        )
        update_job(db, job_id=job_id, rq_job_id=rq_job.id)

        logger.info(
            "Upload saved and queued: filename=%s doc_id=%s job_id=%s size_mb=%.2f",
            file.filename,
            doc_id,
            job_id,
            len(file_bytes) / (1024 * 1024),
        )
        results.append(document_to_response(document, current_job_id=job_id))

    return results


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(JobRecord, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_to_response(job)


@app.get("/api/documents")
async def list_documents(db: Session = Depends(get_db)):
    documents = db.query(DocumentRecord).order_by(desc(DocumentRecord.created_at)).all()
    latest_jobs = {}
    for job in (
        db.query(JobRecord)
        .filter(JobRecord.document_id.isnot(None))
        .order_by(desc(JobRecord.created_at))
        .all()
    ):
        if job.document_id and job.document_id not in latest_jobs:
            latest_jobs[job.document_id] = job.id
    docs = [
        document_to_response(document, current_job_id=latest_jobs.get(document.id))
        for document in documents
    ]
    return {"documents": docs, "total": len(docs)}


@app.get("/api/documents/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str, db: Session = Depends(get_db)):
    document = db.get(DocumentRecord, doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document_to_response(document)


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str, db: Session = Depends(get_db)):
    document = db.get(DocumentRecord, doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if os.path.exists(document.file_path):
        os.remove(document.file_path)
    delete_vectorstore(doc_id)
    db.delete(document)
    db.commit()
    logger.info("Document deleted: doc_id=%s filename=%s", doc_id, document.filename)
    return {"message": "Document deleted"}


@app.delete("/api/documents")
async def delete_all_documents(db: Session = Depends(get_db)):
    documents = db.query(DocumentRecord).all()
    for document in documents:
        if os.path.exists(document.file_path):
            try:
                os.remove(document.file_path)
            except Exception:
                logger.exception("Failed to remove upload during delete-all: doc_id=%s", document.id)
        try:
            delete_vectorstore(document.id)
        except Exception:
            logger.exception("Failed to remove vectorstore during delete-all: doc_id=%s", document.id)
        db.delete(document)

    db.commit()
    logger.info("All documents deleted")
    return {"message": "All documents deleted"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    if not request.document_ids:
        request.document_ids = [
            document.id
            for document in db.query(DocumentRecord)
            .filter(DocumentRecord.status == DocumentStatus.READY.value)
            .all()
        ]
        if not request.document_ids:
            raise HTTPException(
                status_code=400,
                detail="No documents available. Upload and process documents first.",
            )

    documents = (
        db.query(DocumentRecord)
        .filter(DocumentRecord.id.in_(request.document_ids))
        .all()
    )
    documents_by_id = {document.id: document for document in documents}

    for doc_id in request.document_ids:
        document = documents_by_id.get(doc_id)
        if not document:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
        if document.status != DocumentStatus.READY.value:
            raise HTTPException(status_code=400, detail=f"Document {doc_id} not ready")

    session_id = "_".join(sorted(request.document_ids))
    history = chat_histories.get(session_id, [])

    result = run_study_agent(
        db=db,
        query=request.query,
        document_ids=request.document_ids,
        documents_by_id=documents_by_id,
        history=history,
    )
    answer = result["answer"]
    sources = result.get("sources", [])
    sources = sources[:5]
    logger.info(
        "Chat response generated: intent=%s tools=%s sources=%s",
        result.get("intent"),
        result.get("used_tools", []),
        len(sources),
    )

    chat_histories[session_id] = history + [(request.query, answer)]
    return ChatResponse(
        answer=answer,
        sources=sources,
        model=OPENAI_MODEL,
        intent=result.get("intent"),
        used_tools=result.get("used_tools", []),
    )
