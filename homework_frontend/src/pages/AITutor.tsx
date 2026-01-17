import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { apiClient } from '@/services/api';
import { cn } from '@/lib/utils';
import { Header } from '@/components/ui/Header';
import { MathText } from '@/components/ui/MathText';
import { QuestionText } from '@/components/ui/QuestionText';
import type { QuestionCard, SubmissionDetail } from '@/services/types';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

type ServerMessage = { role?: string; content?: string };
type ChatEventPayload = {
  messages?: ServerMessage[];
  session_id?: string | null;
};

const AITutor: React.FC = () => {
  const navigate = useNavigate();
  const { id } = useParams();
  const location = useLocation();
  const [card, setCard] = useState<QuestionCard | null>((location.state as any)?.card || null);
  const submissionId = (location.state as any)?.submissionId || '';
  const [subject, setSubject] = useState((location.state as any)?.subject || 'math');
  const [submission, setSubmission] = useState<SubmissionDetail | null>(null);
  const [fullQuestion, setFullQuestion] = useState<any>(null);

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  
  // Persist sessionId per question (submissionId + itemId) to preserve chat history
  const sessionStorageKey = submissionId && id ? `chat_session_${submissionId}_${id}` : null;
  const [sessionId, setSessionId] = useState<string | null>(() => {
    if (!sessionStorageKey) return null;
    return localStorage.getItem(sessionStorageKey);
  });
  const [errorText, setErrorText] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const messagesRef = useRef<Message[]>([]);

  useEffect(() => {
    if (sessionId && sessionStorageKey) {
      localStorage.setItem(sessionStorageKey, sessionId);
    }
  }, [sessionId, sessionStorageKey]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    const load = async () => {
      if (!submissionId || !id) return;
      if (submission) return;
      try {
        const res = await apiClient.get<SubmissionDetail>(`/submissions/${submissionId}`);
        setSubmission(res.data);
        if (res.data?.subject) setSubject(String(res.data.subject));
        const q = (res.data.questions || []).find((x: any) => String(x?.item_id || '') === String(id)) || null;
        setFullQuestion(q);
        const c = res.data.question_cards?.find((x) => x.item_id === String(id)) || null;
        if (c) setCard(c);
      } catch (err) {
        console.error(err);
      }
    };
    load();
  }, [submissionId, id, submission]);

  const displayQuestionText = useMemo(() => {
    return (
      String((fullQuestion as any)?.question_text || '').trim() ||
      String((fullQuestion as any)?.question_content || '').trim() ||
      String((card as any)?.question_content || '').trim()
    );
  }, [fullQuestion, card]);

  const toClientMessages = (serverMessages: ServerMessage[]) => {
    const now = new Date().toISOString();
    const normalized = serverMessages
      .map((m) => ({
        role: (String(m?.role || '').toLowerCase() === 'assistant' ? 'assistant' : 'user') as Message['role'],
        content: String(m?.content || ''),
      }))
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .reduce<Array<{ role: Message['role']; content: string }>>((acc, m) => {
        const last = acc[acc.length - 1];
        if (last && last.role === m.role && last.content === m.content) return acc;
        return [...acc, m];
      }, []);

    return normalized.map((m, idx) => ({
        id: `${m.role}-${idx}-${m.content.length}`,
        role: m.role,
        content: m.content,
        timestamp: now,
      }));
  };

  const sendMessage = async () => {
    if (!input.trim() || isStreaming) return;
    setErrorText(null);

    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setIsStreaming(true);

    const history = [...messagesRef.current, userMsg].map((msg) => ({
      role: msg.role === 'assistant' ? 'assistant' : 'user',
      content: msg.content,
    }));

    const payload = {
      history,
      question: userMsg.content,
      subject,
      session_id: sessionId || undefined,
      submission_id: submissionId || undefined,
      mode: 'strict',
      context_item_ids: id ? [id] : undefined,
    };

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch(`${apiClient.defaults.baseURL}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
          'X-User-Id': localStorage.getItem('user_id') || 'dev_user',
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });

      if (!res.ok) {
        const text = await res.text().catch(() => '');
        setErrorText(`AI 服务返回异常（${res.status}）${text ? `：${text.slice(0, 200)}` : ''}`);
        return;
      }
      if (!res.body) {
        setErrorText('AI 服务未返回可读的响应流');
        setIsStreaming(false);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';

        for (const part of parts) {
          const lines = part.split('\n');
          let eventType = 'message';
          const dataLines: string[] = [];
          for (const line of lines) {
            if (line.startsWith('event:')) {
              eventType = line.replace('event:', '').trim();
            } else if (line.startsWith('data:')) {
              dataLines.push(line.replace('data:', '').trim());
            }
          }
          const dataText = dataLines.join('\n');
          if (!dataText) continue;

          if (eventType === 'heartbeat') {
            try {
              const hb = JSON.parse(dataText);
              if (hb?.session_id) setSessionId(String(hb.session_id));
            } catch (err) {
              console.error(err);
            }
          }

          if (eventType === 'chat') {
            try {
              const payload = JSON.parse(dataText) as ChatEventPayload;
              if (payload.session_id) setSessionId(String(payload.session_id));
              if (Array.isArray(payload.messages)) {
                setMessages(toClientMessages(payload.messages));
              }
            } catch (err) {
              console.error(err);
            }
          }

          if (eventType === 'done') {
            try {
              const donePayload = JSON.parse(dataText) as { session_id?: string | null };
              if (donePayload?.session_id) setSessionId(String(donePayload.session_id));
            } catch {
              // ignore
            }
            setIsStreaming(false);
          }
        }
      }
    } catch (err) {
      console.error(err);
      const msg = err instanceof Error ? err.message : String(err);
      setErrorText(`请求失败：${msg}`);
    } finally {
      setIsStreaming(false);
    }
  };

  return (
    <div className="min-h-[100dvh] w-full bg-neu-bg text-neu-text flex flex-col overflow-hidden selection:bg-primary/20">
      <Header title="AI 辅导" onBack={() => navigate(-1)} className="bg-neu-bg/90 backdrop-blur-sm sticky top-0 z-20" />

      <div className="flex-1 min-h-0 overflow-y-auto w-full px-4 sm:px-6 py-6 space-y-6 no-scrollbar pb-24">
        {displayQuestionText && (
          <div className="w-full max-w-4xl mx-auto rounded-2xl bg-neu-bg shadow-neu-flat p-4 text-xs text-neu-text-secondary border border-white/40">
            <span className="font-bold">题目：</span>
            <QuestionText as="div" className="mt-2 text-xs text-neu-text-secondary clamp-4" text={displayQuestionText} />
          </div>
        )}

        {errorText && (
          <div className="w-full max-w-4xl mx-auto rounded-2xl bg-neu-bg shadow-neu-pressed p-4 text-xs text-red-500 border border-white/40">
            {errorText}
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            className={cn(
              'flex w-full max-w-4xl mx-auto',
              msg.role === 'user' ? 'justify-end' : 'justify-start'
            )}
          >
            <div
              className={cn(
                'max-w-[80%] p-4 rounded-2xl text-sm leading-relaxed border border-white/40',
                msg.role === 'user'
                  ? 'bg-neu-bg shadow-neu-pressed text-neu-text rounded-br-none'
                  : 'bg-neu-bg shadow-neu-flat text-neu-text rounded-bl-none'
              )}
            >
              <MathText as="div" className="text-sm leading-relaxed text-neu-text" text={msg.content} />
            </div>
          </div>
        ))}

        {isStreaming && (
          <div className="flex justify-start w-full max-w-4xl mx-auto">
            <div className="bg-neu-bg shadow-neu-flat px-4 py-3 rounded-2xl rounded-bl-none flex items-center gap-1.5 border border-white/40">
              <div className="w-2 h-2 rounded-full bg-neu-text-secondary/40 animate-bounce"></div>
              <div className="w-2 h-2 rounded-full bg-neu-text-secondary/40 animate-bounce delay-100"></div>
              <div className="w-2 h-2 rounded-full bg-neu-text-secondary/40 animate-bounce delay-200"></div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="w-full bg-neu-bg shrink-0 z-20 pb-8 pt-2 border-t border-white/50 shadow-[0_-10px_30px_rgba(0,0,0,0.05)] sticky bottom-0">
        <div className="px-4 sm:px-6">
          <div className="max-w-4xl mx-auto flex items-end gap-3">
            <div className="flex-1 bg-neu-bg rounded-[1.5rem] shadow-neu-input transition-all flex items-center min-h-[52px] border border-transparent focus-within:border-transparent">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask a follow-up question..."
                rows={1}
                className="w-full bg-transparent border-none focus:ring-0 outline-none focus:outline-none text-sm px-5 py-3 placeholder:text-neu-text-secondary/50 text-neu-text leading-relaxed resize-none max-h-32"
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                  }
                }}
              />
            </div>
            <button
              type="button"
              onClick={sendMessage}
              disabled={!input.trim() || isStreaming}
              className={cn(
                'size-12 rounded-full bg-neu-bg shadow-neu-flat active:shadow-neu-pressed transition-all shrink-0 flex items-center justify-center border border-white/50 text-neu-text',
                (!input.trim() || isStreaming) && 'opacity-50 grayscale pointer-events-none'
              )}
            >
              <span className="material-symbols-outlined text-[24px] ml-0.5 text-neu-text">send</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AITutor;
