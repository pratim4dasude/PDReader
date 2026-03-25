# 📄 PDReader - AI-Powered PDF Q&A

<p align="center">
  <img src="https://img.shields.io/badge/Stack-FastAPI%20%2B%20React-blue?style=for-the-badge" alt="Stack" />
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License" />
  <img src="https://img.shields.io/badge/Python-3.11+-yellow?style=for-the-badge" alt="Python" />
  <img src="https://img.shields.io/badge/Status-Active-brightgreen?style=for-the-badge" alt="Status" />
</p>

> Upload any PDF and chat with it using AI. PDReader uses Retrieval-Augmented Generation (RAG) to understand your documents and answer questions accurately.

## ✨ Features

- 📤 **Drag & Drop Upload** - Simply drop your PDFs into the interface
- 🔄 **Smart Processing** - Automatically extracts text, chunks content, and creates embeddings
- 💬 **Natural Chat** - Ask questions in plain English and get relevant answers
- 📚 **Multi-Document Support** - Chat with multiple PDFs at once
- 🔍 **Source Citations** - See exactly which parts of the document the answer came from
- 🗃️ **Document Management** - View, delete, and manage your uploaded documents
- 💾 **Persistent Storage** - Documents and their vector stores are saved locally
- 🔐 **Privacy-First** - Your documents stay on your machine

## 🛠️ Tech Stack

### Backend
| Technology | Purpose |
|------------|---------|
| [FastAPI](https://fastapi.tiangolo.com/) | High-performance API framework |
| [LangChain](https://python.langchain.com/) | LLM framework & document processing |
| [FAISS](https://github.com/facebookresearch/faiss) | Vector similarity search |
| [OpenAI](https://openai.com/) | GPT models for embeddings & chat |
| [PyPDF](https://pypdf.readthedocs.io/) | PDF text extraction |

### Frontend
| Technology | Purpose |
|------------|---------|
| [React](https://react.dev/) | UI framework |
| [TypeScript](https://www.typescriptlang.org/) | Type safety |
| [Tailwind CSS](https://tailwindcss.com/) | Styling |
| [Vite](https://vitejs.dev/) | Build tool |
| [Lucide React](https://lucide.dev/) | Icons |

## 🚀 Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- OpenAI API Key ([Get one here](https://platform.openai.com/api-keys))

### Installation

#### 1. Clone the repository
```bash
git clone https://github.com/yourusername/PDReader.git
cd PDReader
```

#### 2. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Mac/Linux)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

#### 3. Configure API Key

```bash
# Copy the example env file
cp .env.example .env

# Edit .env and add your OpenAI API key
OPENAI_API_KEY=sk-your-api-key-here
```

#### 4. Start Backend

```bash
uvicorn main:app --reload --port 8000
```

#### 5. Frontend Setup (in a new terminal)

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

### 🎉 Usage

1. Open **http://localhost:5173** in your browser
2. Upload a PDF using the drag & drop zone or file picker
3. Wait for the document status to show "ready" (processing happens automatically)
4. Ask questions about your document in the chat box
5. View source citations to see where answers came from

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/api/documents/upload` | Upload PDF(s) |
| `GET` | `/api/documents` | List all documents |
| `GET` | `/api/documents/{id}` | Get document details |
| `DELETE` | `/api/documents/{id}` | Delete a document |
| `DELETE` | `/api/documents` | Delete all documents |
| `POST` | `/api/chat` | Ask a question |

### Example: Chat Request

```json
POST /api/chat
{
  "query": "What is this document about?",
  "document_ids": ["doc-uuid-1", "doc-uuid-2"]
}
```

### Example Response

```json
{
  "answer": "This document is an annual report...",
  "sources": [
    {
      "document_id": "doc-uuid-1",
      "filename": "report.pdf",
      "chunk_text": "Annual Report 2024...",
      "page": 1
    }
  ],
  "model": "gpt-3.5-turbo"
}
```

## 📁 Project Structure

```
PDReader/
├── backend/
│   ├── main.py          # FastAPI application & routes
│   ├── services.py      # PDF processing & LLM logic
│   ├── schemas.py       # Pydantic models
│   ├── requirements.txt # Python dependencies
│   └── .env             # Environment variables
├── frontend/
│   ├── src/
│   │   ├── App.tsx      # Main React component
│   │   ├── api.ts       # API client functions
│   │   ├── types.ts     # TypeScript types
│   │   └── index.css    # Global styles
│   ├── package.json     # Node dependencies
│   └── vite.config.ts   # Vite configuration
└── README.md
```

## ⚙️ Configuration

Customize behavior by editing `backend/services.py`:

| Variable | Default | Description |
|----------|---------|-------------|
| `CHUNK_SIZE` | 500 | Text chunk size for embeddings |
| `CHUNK_OVERLAP` | 50 | Overlap between chunks |
| `TOP_K` | 4 | Number of documents to retrieve |
| `OPENAI_MODEL` | gpt-3.5-turbo | LLM model to use |

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- [LangChain](https://python.langchain.com/) for the amazing RAG abstractions
- [FAISS](https://github.com/facebookresearch/faiss) for efficient similarity search
- [OpenAI](https://openai.com/) for the LLM capabilities

---

<p align="center">Made with ❤️ for easier document reading</p>