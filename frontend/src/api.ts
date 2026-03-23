import axios from 'axios';
import type { Document, ChatResponse, HealthResponse } from '../types';

const api = axios.create({ baseURL: '/api' });

export const documentApi = {
  upload: async (files: File | File[]): Promise<Document[]> => {
    const formData = new FormData();
    const fileList = Array.isArray(files) ? files : [files];
    fileList.forEach(file => formData.append('files', file));
    const { data } = await api.post<Document[]>('/documents/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },

  list: async () => {
    const { data } = await api.get<{ documents: Document[]; total: number }>('/documents');
    return data;
  },

  delete: async (id: string) => api.delete(`/documents/${id}`),
  
  deleteAll: async () => api.delete('/documents'),
};

export const chatApi = {
  send: async (query: string, documentIds?: string[]): Promise<ChatResponse> => {
    const { data } = await api.post<ChatResponse>('/chat', { query, document_ids: documentIds });
    return data;
  },
};

export const healthApi = {
  check: async (): Promise<HealthResponse> => {
    const { data } = await api.get<HealthResponse>('/health');
    return data;
  },
};
