import logging

from db import SessionLocal
from repositories import replace_document_content, update_document_status, update_job
from models import DocumentRecord
from services import (
    create_embeddings,
    generate_document_summary_and_topics,
    process_pdf_for_ingestion,
)

logger = logging.getLogger("pdreader.tasks")


def process_document_job(job_id: str, doc_id: str, file_path: str, filename: str) -> None:
    db = SessionLocal()
    try:
        logger.info("RQ processing started: job_id=%s doc_id=%s", job_id, doc_id)
        document = db.get(DocumentRecord, doc_id)
        if not document:
            raise ValueError(f"Document row not found for doc_id={doc_id}; the upload may have been deleted")

        file_path = document.file_path or file_path
        update_job(
            db,
            job_id=job_id,
            status="processing",
            progress=10,
            increment_attempts=True,
        )
        update_document_status(db, doc_id=doc_id, status="processing")

        pages, chunks, page_count, overview = process_pdf_for_ingestion(file_path, filename)
        update_job(db, job_id=job_id, progress=35)

        summary, topic_map = generate_document_summary_and_topics(filename, overview)
        update_job(db, job_id=job_id, progress=50)

        embeddings = create_embeddings([chunk.page_content for chunk in chunks])
        replace_document_content(
            db,
            doc_id=doc_id,
            pages=pages,
            chunks=chunks,
            embeddings=embeddings,
        )
        update_job(db, job_id=job_id, progress=75)

        update_document_status(
            db,
            doc_id=doc_id,
            status="ready",
            page_count=page_count,
            chunk_count=len(chunks),
            summary=summary or overview,
            topic_map=topic_map,
        )
        update_job(db, job_id=job_id, status="completed", progress=100)
        logger.info("RQ processing completed: job_id=%s doc_id=%s", job_id, doc_id)
    except Exception as exc:
        logger.exception("RQ processing failed: job_id=%s doc_id=%s", job_id, doc_id)
        db.rollback()
        try:
            update_document_status(
                db,
                doc_id=doc_id,
                status="error",
                error_message=str(exc),
            )
            update_job(
                db,
                job_id=job_id,
                status="failed",
                error_message=str(exc),
            )
        except Exception:
            db.rollback()
            logger.exception("Failed to persist job failure status: job_id=%s doc_id=%s", job_id, doc_id)
        raise
    finally:
        db.close()
