from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config import settings
from db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DocumentRecord(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    page_count: Mapped[Optional[int]] = mapped_column(Integer)
    chunk_count: Mapped[Optional[int]] = mapped_column(Integer)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    topic_map: Mapped[Optional[dict]] = mapped_column(JSONB)
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    pages: Mapped[list["PageRecord"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )
    chunks: Mapped[list["ChunkRecord"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class PageRecord(Base, TimestampMixin):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    document: Mapped[DocumentRecord] = relationship(back_populates="pages")


class ChunkRecord(Base, TimestampMixin):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_start: Mapped[Optional[int]] = mapped_column(Integer)
    page_end: Mapped[Optional[int]] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(64), nullable=False, default="body")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(settings.embedding_dimensions)
    )
    search_vector: Mapped[Optional[str]] = mapped_column(TSVECTOR)
    extra_metadata: Mapped[Optional[dict]] = mapped_column(JSONB)

    document: Mapped[DocumentRecord] = relationship(back_populates="chunks")


class JobRecord(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"),
        index=True,
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    rq_job_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ChatSessionRecord(Base, TimestampMixin):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[Optional[str]] = mapped_column(String(512))

    messages: Mapped[list["ChatMessageRecord"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )


class ChatMessageRecord(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[Optional[str]] = mapped_column(String(64))
    citations: Mapped[Optional[dict]] = mapped_column(JSONB)

    session: Mapped[ChatSessionRecord] = relationship(back_populates="messages")
