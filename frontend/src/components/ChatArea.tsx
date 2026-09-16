import React, { useEffect, useRef, useState } from 'react';
import { AssistantRuntimeProvider, type ChatModelAdapter, useLocalRuntime } from '@assistant-ui/react';
import { ArrowUp, FileText, Sparkles } from 'lucide-react';
import { ApiError, sendChatMessage } from '../api';
import { Citation } from '../types';
import { EvidenceRail } from './EvidenceRail';

interface ChatAreaProps {
  workspaceName: string;
  onSelectPromptQuery?: string | null;
  onClearSelectedPrompt?: () => void;
  onUnauthorized?: () => void;
}

type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  citations?: Citation[];
  confidence_score?: number;
  receipt_id?: string;
  sufficient_evidence?: boolean;
};

export const ChatArea: React.FC<ChatAreaProps> = ({
  workspaceName,
  onSelectPromptQuery,
  onClearSelectedPrompt,
  onUnauthorized,
}) => {
  const [messagesList, setMessagesList] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [input, setInput] = useState('');
  const [activeMessageId, setActiveMessageId] = useState<string | null>(null);
  const [isMobileEvidenceOpen, setIsMobileEvidenceOpen] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const adapter: ChatModelAdapter = {
    async run({ messages }) {
      const lastMessage = messages[messages.length - 1];
      const query = typeof lastMessage.content === 'string'
        ? lastMessage.content
        : (lastMessage.content as Array<{ type?: string; text?: string }>)
          .filter((part) => part.type === 'text')
          .map((part) => part.text || '')
          .join('\n');

      try {
        const response = await sendChatMessage(query);
        const assistantId = `assistant-${Date.now()}`;
        const assistantMessage: ChatMessage = {
          id: assistantId,
          role: 'assistant',
          content: response.answer,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          citations: response.citations || [],
          confidence_score: response.confidence_score,
          receipt_id: response.retrieval_receipt_id || response.receipt?.receipt_id,
          sufficient_evidence: response.sufficient_evidence ?? Boolean(response.citations?.length),
        };
        setMessagesList((current) => [...current, assistantMessage]);
        setActiveMessageId(assistantId);
        return { content: [{ type: 'text', text: response.answer }] };
      } catch (error: unknown) {
        if (error instanceof ApiError && error.status === 401) onUnauthorized?.();
        const assistantId = `error-${Date.now()}`;
        const message = error instanceof Error ? error.message : 'Thread could not complete that request.';
        setMessagesList((current) => [...current, {
          id: assistantId,
          role: 'assistant',
          content: message,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          citations: [],
          sufficient_evidence: false,
        }]);
        setActiveMessageId(assistantId);
        return { content: [{ type: 'text', text: message }] };
      } finally {
        setLoading(false);
      }
    },
  };

  const runtime = useLocalRuntime(adapter);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messagesList, loading]);

  useEffect(() => {
    if (!onSelectPromptQuery) return;
    sendMessage(onSelectPromptQuery);
    onClearSelectedPrompt?.();
  }, [onSelectPromptQuery]);

  const sendMessage = (text: string) => {
    const query = text.trim();
    if (!query || loading) return;
    setMessagesList((current) => [...current, {
      id: `user-${Date.now()}`,
      role: 'user',
      content: query,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    }]);
    setLoading(true);
    runtime.thread.append({ role: 'user', content: [{ type: 'text', text: query }] });
  };

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    sendMessage(input);
    setInput('');
  };

  const activeMessage = messagesList.find((message) => message.id === activeMessageId)
    || messagesList.slice().reverse().find((message) => message.role === 'assistant');

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="flex h-[calc(100svh-7.5rem)] min-h-[34rem] flex-1 overflow-hidden bg-[#0a0a0a]">
        <section className="flex min-w-0 flex-1 flex-col">
          <div className="flex-1 overflow-y-auto px-5 py-8 sm:px-8 lg:px-10">
            <div className="mx-auto w-full max-w-[110rem]">
              {messagesList.length === 0 ? (
                <div className="flex min-h-[24rem] flex-col justify-center">
                  <div className="flex items-center gap-2 text-sm text-neutral-500">
                    <Sparkles className="h-4 w-4" aria-hidden="true" />
                    ThreadAgent
                  </div>
                  <h1 className="mt-5 max-w-xl text-3xl font-medium leading-tight text-neutral-100 sm:text-5xl">What would you like to know?</h1>
                  <p className="mt-5 max-w-xl text-lg leading-8 text-neutral-400">
                    Ask about the public context connected to {workspaceName}, or use one of the prompts in the workspace rail.
                  </p>
                </div>
              ) : (
                <div className="space-y-12 pb-8">
                  {messagesList.map((message) => (
                    <article
                      key={message.id}
                      onClick={() => message.role === 'assistant' && setActiveMessageId(message.id)}
                      className={message.role === 'user' ? 'ml-auto max-w-[62%]' : 'mt-2 max-w-[68%]'}
                    >
                      <div className="flex items-center gap-3 text-sm text-neutral-500">
                        <span>{message.role === 'user' ? 'You' : 'ThreadAgent'}</span>
                        <span>{message.timestamp}</span>
                      </div>
                      <div className={`mt-3 whitespace-pre-line text-base leading-7 ${message.role === 'user' ? 'border-l border-neutral-700 pl-4 text-neutral-300' : 'text-neutral-100'}`}>
                        {message.content}
                      </div>
                      {message.role === 'assistant' && message.citations && message.citations.length > 0 && (
                        <button
                          onClick={() => {
                            setActiveMessageId(message.id);
                            setIsMobileEvidenceOpen(true);
                          }}
                          className="mt-5 inline-flex items-center gap-2 text-sm text-neutral-400 transition-colors hover:text-neutral-100"
                        >
                          <FileText className="h-4 w-4" aria-hidden="true" />
                          {message.citations.length} supporting source{message.citations.length === 1 ? '' : 's'}
                        </button>
                      )}
                    </article>
                  ))}
                </div>
              )}
              {loading && <p className="mt-8 text-sm text-neutral-500">Thread is checking the available context.</p>}
              <div ref={messagesEndRef} />
            </div>
          </div>

          <div className="border-t border-neutral-800 px-5 py-5 sm:px-8 lg:px-12">
            <div className="mx-auto max-w-3xl">
              <form onSubmit={handleSubmit} className="flex items-center border border-neutral-700 bg-[#111111] focus-within:border-neutral-400">
                <input
                  type="text"
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  placeholder="Ask Thread anything about this community"
                  disabled={loading}
                  className="min-w-0 flex-1 bg-transparent px-4 py-4 text-base text-neutral-100 outline-none placeholder:text-neutral-600 disabled:opacity-50"
                />
                <button type="submit" title="Send message" disabled={!input.trim() || loading} className="mr-2 grid h-9 w-9 place-items-center bg-neutral-100 text-neutral-950 transition-colors hover:bg-white disabled:opacity-30">
                  <ArrowUp className="h-4 w-4" aria-hidden="true" />
                </button>
              </form>
              <div className="mt-3 flex items-center justify-between text-xs text-neutral-600">
                <span>Answers use only the records available to this session.</span>
                {activeMessage && <button onClick={() => setIsMobileEvidenceOpen(true)} className="text-neutral-400 transition-colors hover:text-neutral-100 xl:hidden">View sources</button>}
              </div>
            </div>
          </div>
        </section>

        {activeMessage && (
          <EvidenceRail
            citations={activeMessage.citations || []}
            confidenceScore={activeMessage.confidence_score}
            receiptId={activeMessage.receipt_id}
            sufficientEvidence={activeMessage.sufficient_evidence}
            isOpenMobile={isMobileEvidenceOpen}
            onCloseMobile={() => setIsMobileEvidenceOpen(false)}
            hasActiveResponse
          />
        )}
      </div>
    </AssistantRuntimeProvider>
  );
};
