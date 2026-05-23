from datetime import datetime
from typing import Optional

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from models import ChunkRecord, DocumentRecord, JobRecord, PageRecord


def sanitize_text(value: str) -> str:
    return value.replace("\x00", "")


def sanitize_metadata(value):
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return {key: sanitize_metadata(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_metadata(item) for item in value]
    return value


def create_document(
    db: Session,
    *,
    doc_id: str,
    filename: str,
    file_path: str,
    status: str,
) -> DocumentRecord:
    document = DocumentRecord(
        id=doc_id,
        filename=filename,
        file_path=file_path,
        status=status,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def update_document_status(
    db: Session,
    *,
    doc_id: str,
    status: str,
    error_message: Optional[str] = None,
    page_count: Optional[int] = None,
    chunk_count: Optional[int] = None,
    summary: Optional[str] = None,
    topic_map: Optional[dict] = None,
) -> None:
    document = db.get(DocumentRecord, doc_id)
    if not document:
        return

    document.status = status
    document.error_message = error_message
    if page_count is not None:
        document.page_count = page_count
    if chunk_count is not None:
        document.chunk_count = chunk_count
    if summary is not None:
        document.summary = summary
    if topic_map is not None:
        document.topic_map = topic_map
    document.updated_at = datetime.utcnow()
    db.commit()


def create_job(
    db: Session,
    *,
    job_id: str,
    document_id: Optional[str],
    job_type: str,
    status: str,
    progress: int = 0,
) -> JobRecord:
    job = JobRecord(
        id=job_id,
        document_id=document_id,
        job_type=job_type,
        status=status,
        progress=progress,
        attempts=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_job(
    db: Session,
    *,
    job_id: str,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    error_message: Optional[str] = None,
    rq_job_id: Optional[str] = None,
    increment_attempts: bool = False,
) -> None:
    job = db.get(JobRecord, job_id)
    if not job:
        return

    if status is not None:
        job.status = status
    if progress is not None:
        job.progress = progress
    if error_message is not None:
        job.error_message = error_message
    if rq_job_id is not None:
        job.rq_job_id = rq_job_id
    if increment_attempts:
        job.attempts += 1
    job.updated_at = datetime.utcnow()
    db.commit()


def replace_document_content(
    db: Session,
    *,
    doc_id: str,
    pages: list[Document],
    chunks: list[Document],
    embeddings: list[list[float]],
) -> None:
    if len(chunks) != len(embeddings):
        raise ValueError(
            f"Chunk/embedding count mismatch: chunks={len(chunks)} embeddings={len(embeddings)}"
        )

    db.query(PageRecord).filter(PageRecord.document_id == doc_id).delete()
    db.query(ChunkRecord).filter(ChunkRecord.document_id == doc_id).delete()

    for page in pages:
        page_index = page.metadata.get("page", 0)
        db.add(
            PageRecord(
                document_id=doc_id,
                page_number=page_index + 1 if isinstance(page_index, int) else 0,
                text=sanitize_text(page.page_content),
            )
        )

    for chunk, embedding in zip(chunks, embeddings):
        page_index = chunk.metadata.get("page")
        page_number = page_index + 1 if isinstance(page_index, int) else None
        db.add(
            ChunkRecord(
                document_id=doc_id,
                page_start=page_number,
                page_end=page_number,
                chunk_index=int(chunk.metadata.get("chunk_index", 0)),
                chunk_type="body",
                text=sanitize_text(chunk.page_content),
                embedding=embedding,
                extra_metadata=sanitize_metadata(dict(chunk.metadata)),
            )
        )

    db.commit()
