import logging
import os
import json
import re
import uuid
from pathlib import Path
from typing import List, Tuple

from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings

logger = logging.getLogger("pdreader.services")

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")
load_dotenv()

UPLOAD_DIR = str(BASE_DIR / "uploads")
VECTORSTORE_DIR = str(BASE_DIR / "vectorstores")
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
TOP_K = 8
OVERVIEW_PAGES = 15
MAX_OVERVIEW_CHARS = 12000
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = settings.openai_chat_model

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(VECTORSTORE_DIR, exist_ok=True)

# ============ Document Processing ============


def sanitize_text(value: str) -> str:
    value = value.replace("\x00", "")
    value = value.replace("\x08", "")
    return value


def sanitize_metadata(value):
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return {key: sanitize_metadata(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_metadata(item) for item in value]
    return value


def load_pdf(file_path: str) -> List[Document]:
    logger.info("Loading PDF: path=%s", file_path)
    loader = PyPDFLoader(file_path)
    documents = loader.load()
    for document in documents:
        document.page_content = sanitize_text(document.page_content)
        document.metadata = sanitize_metadata(document.metadata)
    logger.info("PDF loaded: path=%s pages=%s", file_path, len(documents))
    return documents


def split_text(documents: List[Document]) -> List[Document]:
    logger.info(
        "Splitting text: pages=%s chunk_size=%s chunk_overlap=%s",
        len(documents),
        CHUNK_SIZE,
        CHUNK_OVERLAP,
    )
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
    )
    chunks = splitter.split_documents(documents)
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = str(uuid.uuid4())
        chunk.metadata["chunk_index"] = i
    logger.info("Text split complete: chunks=%s", len(chunks))
    return chunks


def build_document_overview(documents: List[Document], filename: str) -> str:
    selected_documents = select_overview_documents(documents)
    overview_parts = []
    for document in selected_documents:
        text = " ".join(document.page_content.split())
        if not text:
            continue
        page = document.metadata.get("page")
        page_label = page + 1 if isinstance(page, int) else "unknown"
        overview_parts.append(f"Page {page_label}: {text}")

    overview = "\n\n".join(overview_parts)
    if len(overview) > MAX_OVERVIEW_CHARS:
        overview = overview[:MAX_OVERVIEW_CHARS].rsplit(" ", 1)[0]

    logger.info(
        "Document overview built: filename=%s pages_used=%s chars=%s",
        filename,
        len(selected_documents),
        len(overview),
    )
    return overview


def select_overview_documents(documents: List[Document]) -> List[Document]:
    candidates = documents[:80]
    scored = []
    for index, document in enumerate(candidates):
        text = " ".join(document.page_content.split())
        lowered = text.lower()
        if not text or is_boilerplate_page(lowered):
            continue

        score = 0
        if "table of contents" in lowered:
            score += 5
        if "preface" in lowered:
            score += 5
        if "who this book is for" in lowered:
            score += 5
        if "what this book covers" in lowered:
            score += 4
        if "this chapter covers" in lowered or "following topics" in lowered:
            score += 3
        if "chapter " in lowered:
            score += 2
        if "this book" in lowered:
            score += 2

        if score:
            scored.append((index, score, document))

    if scored:
        scored.sort(key=lambda item: (-item[1], item[0]))
        selected = sorted(scored[:OVERVIEW_PAGES], key=lambda item: item[0])
        return [document for _, _, document in selected]

    non_boilerplate = [
        document
        for document in candidates
        if document.page_content.strip()
        and not is_boilerplate_page(" ".join(document.page_content.lower().split()))
    ]
    return non_boilerplate[:OVERVIEW_PAGES]


def is_boilerplate_page(lowered_text: str) -> bool:
    boilerplate_terms = (
        "all rights reserved",
        "copyright",
        "trademark",
        "packt publishing cannot guarantee",
        "senior publishing product manager",
        "acquisition editor",
        "proofreader",
        "indexer",
        "praise for",
    )
    return any(term in lowered_text for term in boilerplate_terms)


def get_document_overview(file_path: str, filename: str) -> str:
    documents = load_pdf(file_path)
    return build_document_overview(documents, filename)


def process_pdf(file_path: str, filename: str = "") -> Tuple[List[Document], int, str]:
    documents = load_pdf(file_path)
    page_count = len(documents)
    overview = build_document_overview(documents, filename or os.path.basename(file_path))
    chunks = split_text(documents)
    return chunks, page_count, overview


def process_pdf_for_ingestion(
    file_path: str,
    filename: str = "",
) -> Tuple[List[Document], List[Document], int, str]:
    documents = load_pdf(file_path)
    page_count = len(documents)
    overview = build_document_overview(documents, filename or os.path.basename(file_path))
    chunks = split_text(documents)
    return documents, chunks, page_count, overview


def delete_vectorstore(doc_id: str):
    save_path = os.path.join(VECTORSTORE_DIR, doc_id)
    if os.path.exists(save_path):
        for filename in os.listdir(save_path):
            os.remove(os.path.join(save_path, filename))
        os.rmdir(save_path)
        logger.info("Vectorstore deleted: doc_id=%s path=%s", doc_id, save_path)


# ============ LLM (OpenAI) ============


def create_embeddings(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    if not OPENAI_API_KEY or OPENAI_API_KEY == "your_openai_api_key_here":
        raise ValueError("OPENAI_API_KEY is missing or still set to the placeholder value")

    logger.info("Creating embeddings: texts=%s model=%s", len(texts), settings.openai_embedding_model)
    embeddings = OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        api_key=OPENAI_API_KEY,
    )
    return embeddings.embed_documents(texts)


def create_query_embedding(text: str) -> List[float]:
    if not text.strip():
        raise ValueError("Cannot embed an empty query")
    if not OPENAI_API_KEY or OPENAI_API_KEY == "your_openai_api_key_here":
        raise ValueError("OPENAI_API_KEY is missing or still set to the placeholder value")

    logger.info("Creating query embedding: model=%s", settings.openai_embedding_model)
    embeddings = OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        api_key=OPENAI_API_KEY,
    )
    return embeddings.embed_query(text)


def generate_document_summary_and_topics(filename: str, overview: str) -> Tuple[str, dict]:
    if not overview:
        return "", {"topics": []}

    prompt = f"""You are creating study notes for a PDF book.

Return JSON only with this shape:
{{
  "summary": "A detailed 2-4 paragraph overview of what the document is about.",
  "topics": [
    {{"name": "Topic name", "description": "What this topic covers"}}
  ],
  "recommended_questions": ["Question a student should ask"]
}}

Document filename: {filename}

Available front-matter and early-page context:
{overview}
"""

    llm = ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=0.2)
    response = llm.invoke(prompt)
    raw = response.content.strip()
    try:
        data = json.loads(extract_json_object(raw))
    except json.JSONDecodeError:
        logger.warning("Document topic JSON parse failed; storing raw summary text")
        return raw, {"topics": [], "recommended_questions": []}

    summary = str(data.get("summary", "")).strip()
    topic_map = {
        "topics": data.get("topics", []),
        "recommended_questions": data.get("recommended_questions", []),
    }
    logger.info(
        "Document summary generated: filename=%s summary_chars=%s topics=%s",
        filename,
        len(summary),
        len(topic_map["topics"]),
    )
    return summary, topic_map


def extract_json_object(value: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", value, re.DOTALL)
    if fenced:
        return fenced.group(1)

    start = value.find("{")
    end = value.rfind("}")
    if start != -1 and end != -1 and end > start:
        return value[start : end + 1]
    return value


def generate_answer(
    question: str,
    context_docs: List[str],
    chat_history: List[Tuple[str, str]] = None,
) -> str:
    if not context_docs:
        return "No relevant documents found. Please upload and process documents first."

    logger.info(
        "Generating answer: question=%r context_chunks=%s history_items=%s",
        question,
        len(context_docs),
        len(chat_history or []),
    )

    context = "\n\n---\n\n".join(context_docs)

    history_str = ""
    if chat_history:
        for human, ai in chat_history[-5:]:
            history_str += f"Human: {human}\nAssistant: {ai}\n"

    prompt = f"""You are a senior AI study assistant answering questions based on retrieved excerpts and document overviews.

Use the excerpts to answer the user's question directly. For broad questions like "what is this document about",
"important topics", or "summarize this", synthesize the main themes from the provided excerpts and say that the
answer is based on the available overviews and retrieved excerpts. Write useful, specific answers with enough detail
to help the user understand the documents.

The user may also ask practical meta-questions such as how to read the books, what skills are needed, what to focus
on first, or what code projects to practice. For those questions, use the document topics as the grounding and give
reasonable senior-engineer recommendations. Make clear when something is a recommendation instead of a direct quote
from the excerpts.

Rules:
- Never return an empty answer.
- Do not apologize.
- For overview requests, separate the answer by document using clear headings.
- Prefer concise but substantial explanations over one-line answers.
- For reading plans, skill lists, and practice ideas, provide useful guidance even if the exact question is not stated
  verbatim in the excerpts.
- Do not include a "Sources" section; the app renders sources separately.
- If the excerpts are genuinely unrelated to the question, say that the available context does not contain enough
  information for that exact fact, then provide the best next question or study direction.

Retrieved excerpts:
{context}

Chat History:
{history_str}

Question: {question}

Answer using the context above. Do not invent specific facts about a book, but you may infer study guidance from the
topics and summaries."""

    llm = ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=0.7)
    response = llm.invoke(prompt)
    logger.info("Answer generated: chars=%s", len(response.content))
    return response.content
