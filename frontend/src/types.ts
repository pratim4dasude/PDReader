export interface Document {
  id: string;
  filename: string;
  status: 'pending' | 'processing' | 'ready' | 'error';
  created_at: string;
  page_count?: number;
  chunk_count?: number;
  error_message?: string;
  current_job_id?: string;
}

export interface Job {
  id: string;
  document_id?: string;
  job_type: string;
  status: string;
  progress: number;
  error_message?: string;
  rq_job_id?: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: SourceDocument[];
}

export interface SourceDocument {
  document_id: string;
  filename: string;
  chunk_text: string;
  page?: number;
}

export interface ChatResponse {
  answer: string;
  sources: SourceDocument[];
  model: string;
  intent?: string;
  used_tools?: string[];
}

export interface HealthResponse {
  status: string;
  version: string;
  openai_configured: boolean;
}
