import os
import uuid
import aiofiles
import json
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Tuple

from schemas import (
    DocumentResponse, DocumentStatus, ChatRequest, ChatResponse, 
    SourceDocument, HealthResponse
)
from services import (
    process_pdf, create_vectorstore, search_documents, 
    delete_vectorstore, generate_answer, UPLOAD_DIR, VECTORSTORE_DIR, OPENAI_API_KEY
)

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
            vector_path = os.path.join("vectorstores", doc_id)
            if os.path.exists(file_path) and os.path.exists(vector_path):
                valid_docs[doc_id] = doc
            else:
                print(f"⚠️ Removing missing document: {doc_id}")
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except:
                    pass
                try:
                    delete_vectorstore(doc_id)
                except:
                    pass
        documents_store = valid_docs
        save_documents_store()
        
        print(f"📂 Loaded {len(documents_store)} existing documents")
    else:
        clean_orphan_files()
        print("📂 No existing documents found")

def clean_orphan_files():
    for f in os.listdir(UPLOAD_DIR):
        file_path = os.path.join(UPLOAD_DIR, f)
        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
            except:
                pass
    for d in os.listdir(VECTORSTORE_DIR):
        dir_path = os.path.join(VECTORSTORE_DIR, d)
        if os.path.isdir(dir_path):
            try:
                for f in os.listdir(dir_path):
                    os.remove(os.path.join(dir_path, f))
                os.rmdir(dir_path)
            except:
                pass
    print("🧹 Cleaned up orphan files")

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
        openai_configured=bool(api_key and api_key != "your_openai_api_key_here")
    )


@app.post("/api/documents/upload", response_model=List[DocumentResponse])
async def upload_documents(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)):
    results = []
    for file in files:
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files supported")
        
        doc_id = str(uuid.uuid4())
        filename = f"{doc_id}_{file.filename}"
        file_path = os.path.join(UPLOAD_DIR, filename)
        
        async with aiofiles.open(file_path, 'wb') as out_file:
            await out_file.write(await file.read())
        
        documents_store[doc_id] = {
            "id": doc_id,
            "filename": file.filename,
            "status": DocumentStatus.PENDING,
            "created_at": datetime.now(),
            "file_path": file_path
        }
        
        background_tasks.add_task(process_document_task, doc_id, file_path)
        results.append(DocumentResponse(**documents_store[doc_id]))
    
    save_documents_store()
    return results


def process_document_task(doc_id: str, file_path: str):
    try:
        documents_store[doc_id]["status"] = DocumentStatus.PROCESSING
        save_documents_store()
        
        chunks, page_count = process_pdf(file_path)
        create_vectorstore(chunks, doc_id)
        
        documents_store[doc_id].update({
            "status": DocumentStatus.READY,
            "page_count": page_count,
            "chunk_count": len(chunks)
        })
        save_documents_store()
    except Exception as e:
        documents_store[doc_id].update({
            "status": DocumentStatus.ERROR,
            "error_message": str(e)
        })
        save_documents_store()


@app.get("/api/documents")
async def list_documents():
    docs = sorted(
        [DocumentResponse(**doc) for doc in documents_store.values()],
        key=lambda x: x.created_at,
        reverse=True
    )
    return {"documents": docs, "total": len(docs)}


@app.get("/api/documents/{doc_id}")
async def get_document(doc_id: str):
    if doc_id not in documents_store:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse(**documents_store[doc_id])


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str):
    if doc_id not in documents_store:
        raise HTTPException(status_code=404, detail="Document not found")
    
    doc = documents_store[doc_id]
    if os.path.exists(doc.get("file_path", "")):
        os.remove(doc["file_path"])
    
    delete_vectorstore(doc_id)
    del documents_store[doc_id]
    save_documents_store()
    
    return {"message": "Document deleted"}


@app.delete("/api/documents")
async def delete_all_documents():
    global documents_store
    
    for doc_id, doc in list(documents_store.items()):
        if os.path.exists(doc.get("file_path", "")):
            try:
                os.remove(doc["file_path"])
            except:
                pass
        try:
            delete_vectorstore(doc_id)
        except:
            pass
    
    documents_store = {}
    save_documents_store()
    
    return {"message": "All documents deleted"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    
    # Find ready documents
    if not request.document_ids:
        ready_docs = [d for d in documents_store if documents_store[d]["status"] == DocumentStatus.READY]
        if not ready_docs:
            raise HTTPException(status_code=400, detail="No documents available. Upload and process documents first.")
        request.document_ids = ready_docs
    
    # Verify documents exist and are ready
    for doc_id in request.document_ids:
        if doc_id not in documents_store:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
        if documents_store[doc_id]["status"] != DocumentStatus.READY:
            raise HTTPException(status_code=400, detail=f"Document {doc_id} not ready")
    
    # Search for relevant content
    results = search_documents(request.document_ids, request.query)
    
    if not results:
        return ChatResponse(answer="No relevant information found.", sources=[], model="gpt-3.5-turbo")
    
    # Generate answer
    context = [doc.page_content for doc, _ in results]
    session_id = "_".join(sorted(request.document_ids))
    history = chat_histories.get(session_id, [])
    
    answer = generate_answer(request.query, context, history)
    
    chat_histories[session_id] = history + [(request.query, answer)]
    
    # Build sources
    sources = []
    for doc, _ in results:
        doc_id = doc.metadata.get("source_document_id", "")
        sources.append(SourceDocument(
            document_id=doc_id,
            filename=documents_store.get(doc_id, {}).get("filename", "Unknown"),
            chunk_text=doc.page_content[:500] + "..." if len(doc.page_content) > 500 else doc.page_content,
            page=doc.metadata.get("page")
        ))
    
    return ChatResponse(answer=answer, sources=sources, model="gpt-3.5-turbo")
