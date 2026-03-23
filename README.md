# PDReader - Simple PDF Q&A

A simple chatbot that reads PDFs and answers your questions using OpenAI.

## Structure

```
PDReader/
├── backend/
│   ├── main.py          # FastAPI app + all routes (simple!)
│   ├── services.py      # PDF processing, vector store, LLM
│   ├── schemas.py        # Data models
│   ├── requirements.txt
│   └── .env
└── frontend/
    ├── src/
    │   ├── App.tsx      # Everything in one file (easy!)
    │   ├── api.ts       # API calls
    │   └── types.ts     # TypeScript types
    └── package.json
```

## How to Run

### Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Mac/Linux
pip install -r requirements.txt
cp .env.example .env
# Add your OPENAI_API_KEY to .env
uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## What It Does

1. Upload a PDF
2. Wait for "ready" status
3. Ask questions about the PDF
4. Get answers based on the document content

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Check if API is working |
| POST | `/api/documents/upload` | Upload PDF |
| GET | `/api/documents` | List documents |
| DELETE | `/api/documents/{id}` | Delete document |
| POST | `/api/chat` | Ask a question |
