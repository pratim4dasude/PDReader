from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class DocumentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"


class DocumentResponse(BaseModel):
    id: str
    filename: str
    status: DocumentStatus
    created_at: datetime
    page_count: Optional[int] = None
    chunk_count: Optional[int] = None
    error_message: Optional[str] = None
    current_job_id: Optional[str] = None


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1)
    document_ids: Optional[List[str]] = None


class SourceDocument(BaseModel):
    document_id: str
    filename: str
    chunk_text: str
    page: Optional[int] = None


class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceDocument]
    model: str
    intent: Optional[str] = None
    used_tools: List[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    version: str
    openai_configured: bool


class JobResponse(BaseModel):
    id: str
    document_id: Optional[str] = None
    job_type: str
    status: str
    progress: int
    error_message: Optional[str] = None
    rq_job_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
