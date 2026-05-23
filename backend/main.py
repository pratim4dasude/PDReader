import json
import logging
import os
import uuid
from datetime import datetime
from typing import Dict, List, Tuple

import aiofiles
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from schemas import (
    ChatRequest,
    ChatResponse,
    DocumentResponse,
    DocumentStatus,
    HealthResponse,
    SourceDocument,
)
from services import (
    UPLOAD_DIR,
    VECTORSTORE_DIR,
    create_vectorstore,
    delete_vectorstore,
    generate_answer,
    process_pdf,
    search_documents,
)

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

app = FastAPI(title="PDReader API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ Persistence ============

DOCS_FILE = "documents.json"


def load_documents_store() -> Dict[str, dict]:
    if os.path.exists(DOCS_FILE):
        with open(DOCS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_documents_store():
    with open(DOCS_FILE, "w") as f:
        json.dump(documents_store, f, default=str)


def initialize_store():
    global documents_store
    documents_store = load_documents_store()

    if documents_store:
        valid_docs = {}
        for doc_id, doc in documents_store.items():
            file_path = doc.get("file_path", "")
            vector_path = os.path.join(VECTORSTORE_DIR, doc_id)
            if os.path.exists(file_path) and os.path.exists(vector_path):
                valid_docs[doc_id] = doc
            else:
                logger.warning("Removing missing document from store: doc_id=%s", doc_id)
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except Exception:
                    logger.exception("Failed to remove missing upload file: path=%s", file_path)

                try:
                    delete_vectorstore(doc_id)
                except Exception:
                    logger.exception("Failed to remove missing vectorstore: doc_id=%s", doc_id)

        documents_store = valid_docs
        save_documents_store()
        logger.info("Loaded existing documents: count=%s", len(documents_store))
    else:
        clean_orphan_files()
        logger.info("No existing documents found")


def clean_orphan_files():
    for filename in os.listdir(UPLOAD_DIR):
        file_path = os.path.join(UPLOAD_DIR, filename)
        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
            except Exception:
                logger.exception("Failed to remove orphan upload file: path=%s", file_path)

    for dirname in os.listdir(VECTORSTORE_DIR):
        dir_path = os.path.join(VECTORSTORE_DIR, dirname)
        if os.path.isdir(dir_path):
            try:
                for filename in os.listdir(dir_path):
                    os.remove(os.path.join(dir_path, filename))
                os.rmdir(dir_path)
            except Exception:
                logger.exception("Failed to remove orphan vectorstore directory: path=%s", dir_path)

    logger.info("Cleaned up orphan files")


initialize_store()

# ============ Chat History ============

chat_histories: Dict[str, List[Tuple[str, str]]] = {}

# ============ Routes ============


@app.get("/", response_model=HealthResponse)
@app.get("/health", response_model=HealthResponse)
@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    api_key = os.getenv("OPENAI_API_KEY", "")
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        openai_configured=bool(api_key and api_key != "your_openai_api_key_here"),
    )


@app.post("/api/documents/upload", response_model=List[DocumentResponse])
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
):
    results = []
    for file in files:
        if not file.filename.lower().endswith(".pdf"):
            logger.warning("Rejected non-PDF upload: filename=%s", file.filename)
            raise HTTPException(status_code=400, detail="Only PDF files supported")

        doc_id = str(uuid.uuid4())
        filename = f"{doc_id}_{file.filename}"
        file_path = os.path.join(UPLOAD_DIR, filename)
        logger.info("Upload received: filename=%s doc_id=%s", file.filename, doc_id)

        async with aiofiles.open(file_path, "wb") as out_file:
            file_bytes = await file.read()
            await out_file.write(file_bytes)

        logger.info(
            "Upload saved: filename=%s doc_id=%s size_mb=%.2f path=%s",
            file.filename,
            doc_id,
            len(file_bytes) / (1024 * 1024),
            file_path,
        )

        documents_store[doc_id] = {
            "id": doc_id,
            "filename": file.filename,
            "status": DocumentStatus.PENDING,
            "created_at": datetime.now(),
            "file_path": file_path,
        }

        background_tasks.add_task(process_document_task, doc_id, file_path)
        results.append(DocumentResponse(**documents_store[doc_id]))

    save_documents_store()
    return results


def process_document_task(doc_id: str, file_path: str):
    filename = documents_store.get(doc_id, {}).get("filename", doc_id)
    try:
        logger.info("Processing started: filename=%s doc_id=%s", filename, doc_id)

        documents_store[doc_id]["status"] = DocumentStatus.PROCESSING
        save_documents_store()

        chunks, page_count = process_pdf(file_path)
        logger.info(
            "PDF processed: filename=%s doc_id=%s pages=%s chunks=%s",
            filename,
            doc_id,
            page_count,
            len(chunks),
        )

        create_vectorstore(chunks, doc_id)
        logger.info("Vectorstore created: filename=%s doc_id=%s", filename, doc_id)

        documents_store[doc_id].update(
            {
                "status": DocumentStatus.READY,
                "page_count": page_count,
                "chunk_count": len(chunks),
            }
        )
        save_documents_store()
        logger.info("Processing completed: filename=%s doc_id=%s", filename, doc_id)
    except Exception as e:
        logger.exception(
            "Processing failed: filename=%s doc_id=%s error=%s",
            filename,
            doc_id,
            e,
        )
        documents_store[doc_id].update(
            {
                "status": DocumentStatus.ERROR,
                "error_message": str(e),
            }
        )
        save_documents_store()


@app.get("/api/documents")
async def list_documents():
    logger.info("Listing documents: total=%s", len(documents_store))
    docs = sorted(
        [DocumentResponse(**doc) for doc in documents_store.values()],
        key=lambda x: x.created_at,
        reverse=True,
    )
    return {"documents": docs, "total": len(docs)}


@app.get("/api/documents/{doc_id}")
async def get_document(doc_id: str):
    if doc_id not in documents_store:
        logger.warning("Document lookup failed: doc_id=%s", doc_id)
        raise HTTPException(status_code=404, detail="Document not found")

    logger.info(
        "Document lookup: doc_id=%s status=%s",
        doc_id,
        documents_store[doc_id].get("status"),
    )
    return DocumentResponse(**documents_store[doc_id])


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str):
    if doc_id not in documents_store:
        logger.warning("Delete failed; document not found: doc_id=%s", doc_id)
        raise HTTPException(status_code=404, detail="Document not found")

    doc = documents_store[doc_id]
    if os.path.exists(doc.get("file_path", "")):
        os.remove(doc["file_path"])

    delete_vectorstore(doc_id)
    del documents_store[doc_id]
    save_documents_store()
    logger.info("Document deleted: doc_id=%s filename=%s", doc_id, doc.get("filename"))

    return {"message": "Document deleted"}


@app.delete("/api/documents")
async def delete_all_documents():
    global documents_store

    for doc_id, doc in list(documents_store.items()):
        if os.path.exists(doc.get("file_path", "")):
            try:
                os.remove(doc["file_path"])
            except Exception:
                logger.exception("Failed to remove upload during delete-all: doc_id=%s", doc_id)
        try:
            delete_vectorstore(doc_id)
        except Exception:
            logger.exception("Failed to remove vectorstore during delete-all: doc_id=%s", doc_id)

    documents_store = {}
    save_documents_store()
    logger.info("All documents deleted")

    return {"message": "All documents deleted"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    if not request.query.strip():
        logger.warning("Rejected empty chat query")
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    if not request.document_ids:
        ready_docs = [
            doc_id
            for doc_id, doc in documents_store.items()
            if doc["status"] == DocumentStatus.READY
        ]
        if not ready_docs:
            logger.warning("Rejected chat query because no ready documents are available")
            raise HTTPException(
                status_code=400,
                detail="No documents available. Upload and process documents first.",
            )
        request.document_ids = ready_docs

    for doc_id in request.document_ids:
        if doc_id not in documents_store:
            logger.warning("Rejected chat query; document not found: doc_id=%s", doc_id)
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
        if documents_store[doc_id]["status"] != DocumentStatus.READY:
            logger.warning(
                "Rejected chat query; document not ready: doc_id=%s status=%s",
                doc_id,
                documents_store[doc_id]["status"],
            )
            raise HTTPException(status_code=400, detail=f"Document {doc_id} not ready")

    logger.info("Chat request: query=%r document_ids=%s", request.query, request.document_ids)

    results = search_documents(request.document_ids, request.query)

    if not results:
        logger.info("Chat request had no relevant search results")
        return ChatResponse(answer="No relevant information found.", sources=[], model="gpt-3.5-turbo")

    context = [doc.page_content for doc, _ in results]
    session_id = "_".join(sorted(request.document_ids))
    history = chat_histories.get(session_id, [])

    answer = generate_answer(request.query, context, history)
    logger.info("Chat response generated: sources=%s", len(results))

    chat_histories[session_id] = history + [(request.query, answer)]

    sources = []
    for doc, _ in results:
        doc_id = doc.metadata.get("source_document_id", "")
        sources.append(
            SourceDocument(
                document_id=doc_id,
                filename=documents_store.get(doc_id, {}).get("filename", "Unknown"),
                chunk_text=doc.page_content[:500] + "..."
                if len(doc.page_content) > 500
                else doc.page_content,
                page=doc.metadata.get("page"),
            )
        )

    return ChatResponse(answer=answer, sources=sources, model="gpt-3.5-turbo")
