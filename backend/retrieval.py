from dataclasses import dataclass

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from models import ChunkRecord, DocumentRecord
from services import create_query_embedding


@dataclass
class RetrievedChunk:
    document_id: str
    filename: str
    text: str
    page_start: int | None
    page_end: int | None
    score: float
    source: str


def hybrid_search(
    db: Session,
    *,
    document_ids: list[str],
    query: str,
    semantic_k: int = 8,
    keyword_k: int = 8,
    final_k: int = 8,
) -> list[RetrievedChunk]:
    semantic_results = semantic_search(
        db,
        document_ids=document_ids,
        query=query,
        limit=semantic_k,
    )
    keyword_results = keyword_search(
        db,
        document_ids=document_ids,
        query=query,
        limit=keyword_k,
    )
    return fuse_results(semantic_results, keyword_results, final_k=final_k)


def semantic_search(
    db: Session,
    *,
    document_ids: list[str],
    query: str,
    limit: int,
) -> list[RetrievedChunk]:
    query_embedding = create_query_embedding(query)
    distance = ChunkRecord.embedding.cosine_distance(query_embedding).label("distance")

    stmt = (
        select(ChunkRecord, DocumentRecord.filename, distance)
        .join(DocumentRecord, DocumentRecord.id == ChunkRecord.document_id)
        .where(ChunkRecord.document_id.in_(document_ids))
        .where(ChunkRecord.embedding.isnot(None))
        .order_by(distance)
        .limit(limit)
    )

    results = []
    for chunk, filename, raw_distance in db.execute(stmt).all():
        distance_value = float(raw_distance)
        results.append(
            RetrievedChunk(
                document_id=chunk.document_id,
                filename=filename,
                text=chunk.text,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                score=1.0 / (1.0 + distance_value),
                source="semantic",
            )
        )
    return results


def keyword_search(
    db: Session,
    *,
    document_ids: list[str],
    query: str,
    limit: int,
) -> list[RetrievedChunk]:
    ts_query = func.plainto_tsquery("english", query)
    rank = func.ts_rank(ChunkRecord.search_vector, ts_query).label("rank")

    stmt = (
        select(ChunkRecord, DocumentRecord.filename, rank)
        .join(DocumentRecord, DocumentRecord.id == ChunkRecord.document_id)
        .where(ChunkRecord.document_id.in_(document_ids))
        .where(ChunkRecord.search_vector.op("@@")(ts_query))
        .order_by(desc(rank))
        .limit(limit)
    )

    results = []
    for chunk, filename, raw_rank in db.execute(stmt).all():
        results.append(
            RetrievedChunk(
                document_id=chunk.document_id,
                filename=filename,
                text=chunk.text,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                score=float(raw_rank),
                source="keyword",
            )
        )
    return results


def fuse_results(
    semantic_results: list[RetrievedChunk],
    keyword_results: list[RetrievedChunk],
    *,
    final_k: int,
) -> list[RetrievedChunk]:
    fused = {}

    for rank, result in enumerate(semantic_results, start=1):
        key = (result.document_id, result.text)
        existing = fused.get(key)
        score = 1.0 / (rank + 60)
        fused[key] = result if existing is None else existing
        fused[key].score = (existing.score if existing else 0.0) + score
        fused[key].source = "hybrid" if existing else result.source

    for rank, result in enumerate(keyword_results, start=1):
        key = (result.document_id, result.text)
        existing = fused.get(key)
        score = 1.0 / (rank + 60)
        fused[key] = result if existing is None else existing
        fused[key].score = (existing.score if existing else 0.0) + score
        fused[key].source = "hybrid" if existing else result.source

    return sorted(fused.values(), key=lambda item: item.score, reverse=True)[:final_k]
