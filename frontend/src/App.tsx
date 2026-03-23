import { useState, useEffect, useRef } from 'react';
import { FileText, MessageSquare, Upload, X, Send, Bot, User, Loader2, BookOpen } from 'lucide-react';
import { documentApi, chatApi, healthApi } from './api';
import type { Document, Message } from './types';

function App() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [chatLoading, setChatLoading] = useState(false);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    init();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const init = async () => {
    try {
      const healthData = await healthApi.check();
      setHealth(healthData);
      if (healthData.status === 'healthy') {
        const docsData = await documentApi.list();
        setDocuments(docsData.documents);
      }
    } catch {}
    setLoading(false);
  };

  const [polling, setPolling] = useState(false);

  const uploadFile = async (file: File) => {
    setUploading(true);
    setPolling(true);
    try {
      const doc = await documentApi.upload(file);
      setDocuments(prev => [doc, ...prev]);
    } catch (err) {
      console.error(err);
    }
    setUploading(false);
  };

  useEffect(() => {
    if (!polling) return;
    const interval = setInterval(async () => {
      try {
        const data = await documentApi.list();
        setDocuments(data.documents);
        if (!data.documents.some((d: Document) => d.status === 'processing' || d.status === 'pending')) {
          setPolling(false);
        }
      } catch {}
    }, 2000);
    return () => clearInterval(interval);
  }, [polling]);

  const deleteDoc = async (id: string) => {
    await documentApi.delete(id);
    setDocuments(prev => prev.filter(d => d.id !== id));
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  };

  const sendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || chatLoading) return;

    const readyDocs = documents.filter(d => d.status === 'ready');
    if (readyDocs.length === 0) return;

    const userMsg: Message = { id: Date.now().toString(), role: 'user', content: input.trim() };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setChatLoading(true);

    try {
      const response = await chatApi.send(input.trim(), readyDocs.map(d => d.id));
      const assistantMsg: Message = { 
        id: (Date.now() + 1).toString(), 
        role: 'assistant', 
        content: response.answer, 
        sources: response.sources 
      };
      setMessages(prev => [...prev, assistantMsg]);
    } catch {
      setMessages(prev => [...prev, { 
        id: (Date.now() + 1).toString(), 
        role: 'assistant', 
        content: 'Error: Please try again.' 
      }]);
    }
    setChatLoading(false);
  };

  if (loading) {
    return <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
    </div>;
  }

  if (!health?.openai_configured) {
    return <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center p-8 bg-white rounded-lg shadow-lg">
        <h1 className="text-2xl font-bold text-red-600 mb-4">API Key Required</h1>
        <p className="text-gray-600 mb-4">Add your OpenAI API key to backend/.env</p>
        <code className="block bg-gray-100 p-4 rounded">OPENAI_API_KEY=sk-...</code>
      </div>
    </div>;
  }

  const readyCount = documents.filter(d => d.status === 'ready').length;

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center gap-3">
          <FileText className="w-8 h-8 text-blue-500" />
          <h1 className="text-2xl font-bold">PDReader</h1>
          <span className="text-gray-500">PDF Q&A</span>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-6 flex gap-6">
        {/* Sidebar - Documents */}
        <aside className="w-80">
          <div className="bg-white rounded-lg shadow p-4">
            <h2 className="font-semibold mb-4 flex items-center gap-2">
              <FileText className="w-4 h-4" />
              Documents ({readyCount} ready)
            </h2>

            {/* Upload Zone */}
            <div
              className="border-2 border-dashed rounded-lg p-6 text-center mb-4"
              onDragOver={e => e.preventDefault()}
              onDrop={handleDrop}
            >
              <input type="file" accept=".pdf" className="hidden" id="file-input"
                onChange={e => e.target.files?.[0] && uploadFile(e.target.files[0])} />
              <label htmlFor="file-input" className="cursor-pointer flex flex-col items-center gap-2">
                {uploading ? <Loader2 className="w-10 h-10 text-blue-500 animate-spin" />
                  : <Upload className="w-10 h-10 text-gray-400" />}
                <span className="text-gray-600">{uploading ? 'Uploading...' : 'Drop PDF or click'}</span>
              </label>
            </div>

            {/* Document List */}
            <div className="space-y-2">
              {documents.map(doc => (
                <div key={doc.id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                  <div className="flex items-center gap-2">
                    <FileText className="w-4 h-4 text-red-500" />
                    <div>
                      <p className="text-sm font-medium truncate max-w-[180px]">{doc.filename}</p>
                      <p className="text-xs text-gray-500">
                        {doc.status === 'ready' ? `${doc.page_count} pages` : doc.status}
                      </p>
                    </div>
                  </div>
                  <button onClick={() => deleteDoc(doc.id)} className="p-1 hover:bg-gray-200 rounded">
                    <X className="w-4 h-4 text-gray-500" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        </aside>

        {/* Chat Area */}
        <section className="flex-1 bg-white rounded-lg shadow flex flex-col">
          <div className="flex items-center gap-2 px-4 py-3 border-b">
            <MessageSquare className="w-5 h-5 text-gray-500" />
            <span className="font-medium">Chat</span>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-[400px]">
            {messages.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-gray-500">
                <Bot className="w-12 h-12 mb-2" />
                <p>Upload PDFs and ask questions</p>
              </div>
            ) : messages.map(msg => (
              <div key={msg.id} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
                <div className={`w-8 h-8 rounded-full flex items-center justify-center
                  ${msg.role === 'user' ? 'bg-blue-500' : 'bg-gray-200'}`}>
                  {msg.role === 'user' ? <User className="w-4 h-4 text-white" />
                    : <Bot className="w-4 h-4 text-gray-600" />}
                </div>
                <div className={`max-w-[70%] rounded-lg p-3
                  ${msg.role === 'user' ? 'bg-blue-500 text-white' : 'bg-gray-100'}`}>
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                  {msg.sources?.length ? (
                    <div className="mt-2 pt-2 border-t border-gray-300">
                      <p className="text-xs flex items-center gap-1 mb-1">
                        <BookOpen className="w-3 h-3" /> Sources:
                      </p>
                      {msg.sources.map((s, i) => (
                        <div key={i} className="text-xs bg-white rounded p-2 mb-1">
                          <p className="font-medium">{s.filename}</p>
                          <p className="line-clamp-2">{s.chunk_text}</p>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <form onSubmit={sendMessage} className="p-4 border-t flex gap-2">
            <input
              type="text" value={input} onChange={e => setInput(e.target.value)}
              placeholder={readyCount > 0 ? "Ask about your documents..." : "Upload documents first"}
              className="flex-1 px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              disabled={chatLoading || readyCount === 0}
            />
            <button type="submit" disabled={chatLoading || !input.trim() || readyCount === 0}
              className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50">
              {chatLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
            </button>
          </form>
        </section>
      </main>
    </div>
  );
}

export default App;
