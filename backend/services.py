import logging
import os
import uuid
from pathlib import Path
from typing import List, Tuple

from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger("pdreader.services")

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")
load_dotenv()

UPLOAD_DIR = "uploads"
VECTORSTORE_DIR = "vectorstores"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
TOP_K = 4
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = "gpt-3.5-turbo"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(VECTORSTORE_DIR, exist_ok=True)

# ============ Document Processing ============


def load_pdf(file_path: str) -> List[Document]:
    logger.info("Loading PDF: path=%s", file_path)
    loader = PyPDFLoader(file_path)
    documents = loader.load()
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


def process_pdf(file_path: str) -> Tuple[List[Document], int]:
    documents = load_pdf(file_path)
    page_count = len(documents)
    chunks = split_text(documents)
    return chunks, page_count


# ============ Vector Store (FAISS) ============


def create_vectorstore(chunks: List[Document], doc_id: str) -> FAISS:
    logger.info("Creating embeddings/vectorstore: doc_id=%s chunks=%s", doc_id, len(chunks))
    if not OPENAI_API_KEY or OPENAI_API_KEY == "your_openai_api_key_here":
        raise ValueError("OPENAI_API_KEY is missing or still set to the placeholder value")

    embeddings = OpenAIEmbeddings(api_key=OPENAI_API_KEY)
    texts = [chunk.page_content for chunk in chunks]
    metadatas = [chunk.metadata for chunk in chunks]

    vectorstore = FAISS.from_texts(
        texts=texts,
        embedding=embeddings,
        metadatas=metadatas,
    )

    save_path = os.path.join(VECTORSTORE_DIR, doc_id)
    vectorstore.save_local(save_path)
    logger.info("Vectorstore saved: doc_id=%s path=%s", doc_id, save_path)
    return vectorstore


def load_vectorstore(doc_id: str) -> FAISS:
    logger.info("Loading vectorstore: doc_id=%s", doc_id)
    embeddings = OpenAIEmbeddings(api_key=OPENAI_API_KEY)
    save_path = os.path.join(VECTORSTORE_DIR, doc_id)
    return FAISS.load_local(save_path, embeddings, allow_dangerous_deserialization=True)


def search_documents(doc_ids: List[str], query: str, top_k: int = TOP_K) -> List[Tuple[Document, float]]:
    logger.info("Searching documents: query=%r doc_ids=%s top_k=%s", query, doc_ids, top_k)
    all_results = []

    for doc_id in doc_ids:
        try:
            vectorstore = load_vectorstore(doc_id)
            results = vectorstore.similarity_search_with_score(query, k=top_k)
            logger.info("Search results for document: doc_id=%s count=%s", doc_id, len(results))
            for doc, score in results:
                doc.metadata["source_document_id"] = doc_id
                all_results.append((doc, score))
                logger.info(
                    "Search match: doc_id=%s score=%.4f chunk_preview=%r",
                    doc_id,
                    score,
                    doc.page_content[:80],
                )
        except Exception:
            logger.exception("Search failed for document: doc_id=%s", doc_id)

    all_results.sort(key=lambda x: x[1], reverse=True)
    top_results = all_results[:top_k]
    logger.info("Search complete: returned=%s", len(top_results))
    return top_results


def delete_vectorstore(doc_id: str):
    save_path = os.path.join(VECTORSTORE_DIR, doc_id)
    if os.path.exists(save_path):
        for filename in os.listdir(save_path):
            os.remove(os.path.join(save_path, filename))
        os.rmdir(save_path)
        logger.info("Vectorstore deleted: doc_id=%s path=%s", doc_id, save_path)


# ============ LLM (OpenAI) ============


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

    prompt = f"""You are a helpful assistant answering questions based on document context.

Context:
{context}

Chat History:
{history_str}

Question: {question}

Answer based only on the context above. If the context doesn't contain the answer, say so."""

    llm = ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=0.7)
    response = llm.invoke(prompt)
    logger.info("Answer generated: chars=%s", len(response.content))
    return response.content
