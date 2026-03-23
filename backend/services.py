import os
import uuid
from pathlib import Path
from dotenv import load_dotenv
from typing import List, Tuple

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings, ChatOpenAI

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
    loader = PyPDFLoader(file_path)
    return loader.load()

def split_text(documents: List[Document]) -> List[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""]
    )
    chunks = splitter.split_documents(documents)
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = str(uuid.uuid4())
        chunk.metadata["chunk_index"] = i
    return chunks

def process_pdf(file_path: str) -> Tuple[List[Document], int]:
    documents = load_pdf(file_path)
    page_count = len(documents)
    chunks = split_text(documents)
    return chunks, page_count

# ============ Vector Store (FAISS) ============

def create_vectorstore(chunks: List[Document], doc_id: str) -> FAISS:
    embeddings = OpenAIEmbeddings(api_key=OPENAI_API_KEY)
    texts = [c.page_content for c in chunks]
    metadatas = [c.metadata for c in chunks]
    
    vectorstore = FAISS.from_texts(
        texts=texts,
        embedding=embeddings,
        metadatas=metadatas
    )
    
    save_path = os.path.join(VECTORSTORE_DIR, doc_id)
    vectorstore.save_local(save_path)
    return vectorstore

def load_vectorstore(doc_id: str) -> FAISS:
    embeddings = OpenAIEmbeddings(api_key=OPENAI_API_KEY)
    save_path = os.path.join(VECTORSTORE_DIR, doc_id)
    return FAISS.load_local(save_path, embeddings, allow_dangerous_deserialization=True)

def search_documents(doc_ids: List[str], query: str, top_k: int = TOP_K) -> List[Tuple[Document, float]]:
    print(f"\n🔍 Searching for: '{query}'")
    print(f"📚 Searching in documents: {doc_ids}")
    all_results = []
    
    for doc_id in doc_ids:
        try:
            vs = load_vectorstore(doc_id)
            results = vs.similarity_search_with_score(query, k=top_k)
            print(f"   Found {len(results)} results in {doc_id}")
            for doc, score in results:
                doc.metadata["source_document_id"] = doc_id
                all_results.append((doc, score))
                print(f"   - Score: {score:.4f} | Chunk: {doc.page_content[:80]}...")
        except Exception as e:
            print(f"   ❌ Error loading {doc_id}: {e}")
    
    all_results.sort(key=lambda x: x[1], reverse=True)
    top_results = all_results[:top_k]
    print(f"✅ Returning {len(top_results)} best matches\n")
    return top_results

def delete_vectorstore(doc_id: str):
    save_path = os.path.join(VECTORSTORE_DIR, doc_id)
    if os.path.exists(save_path):
        for f in os.listdir(save_path):
            os.remove(os.path.join(save_path, f))
        os.rmdir(save_path)

# ============ LLM (OpenAI) ============

def generate_answer(question: str, context_docs: List[str], chat_history: List[Tuple[str, str]] = None) -> str:
    if not context_docs:
        return "No relevant documents found. Please upload and process documents first."
    
    print(f"📝 Question: {question}")
    print(f"📄 Using {len(context_docs)} context chunks:")
    for i, ctx in enumerate(context_docs):
        print(f"   [{i+1}] {ctx[:150]}...")
    
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
    print(f"🤖 LLM Response: {response.content[:200]}...\n")
    return response.content
