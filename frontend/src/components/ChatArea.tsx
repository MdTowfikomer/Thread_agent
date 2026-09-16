import React, { useState, useRef, useEffect } from 'react';
import { useLocalRuntime, AssistantRuntimeProvider, type ChatModelAdapter } from '@assistant-ui/react';
import { sendChatMessage, ApiError } from '../api';
import { Citation } from '../types';
import { EvidenceRail } from './EvidenceRail';
import { AsciiArt } from '@/components/ui/minimal-2';
import { Send, Terminal, AlertTriangle, ExternalLink } from 'lucide-react';

interface ChatAreaProps {
  workspaceName: string;
  onSelectPromptQuery?: string | null;
  onClearSelectedPrompt?: () => void;
  onUnauthorized?: () => void;
  activeSourceFilter?: string;
}

export const ChatArea: React.FC<ChatAreaProps> = ({
  workspaceName,
  onSelectPromptQuery,
  onClearSelectedPrompt,
  onUnauthorized,
  activeSourceFilter = 'all',
}) => {
  const [messagesList, setMessagesList] = useState<Array<{
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: string;
    citations?: Citation[];
    confidence_score?: number;
    receipt_id?: string;
    sufficient_evidence?: boolean;
    role_agent?: any;
    trace?: any[];
  }>>([]);

  const [loading, setLoading] = useState(false);
  const [input, setInput] = useState('');
  const [activeMessageId, setActiveMessageId] = useState<string | null>(null);
  const [isMobileEvidenceOpen, setIsMobileEvidenceOpen] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Define Assistant UI ChatModelAdapter
  const adapter: ChatModelAdapter = {
    async run({ messages }) {
      const lastMsg = messages[messages.length - 1];
      let queryText = '';
      if (typeof lastMsg.content === 'string') {
        queryText = lastMsg.content;
      } else if (Array.isArray(lastMsg.content)) {
        queryText = (lastMsg.content as any[])
          .filter((part: any) => part.type === 'text')
          .map((part: any) => part.text)
          .join('\n');
      }

      if (activeSourceFilter && activeSourceFilter !== 'all') {
        queryText = `[Filter: ${activeSourceFilter}] ${queryText}`;
      }

      try {
        const response = await sendChatMessage(queryText);
        const assistantId = `assistant-${Date.now()}`;
        
        const customData = {
          citations: response.citations || [],
          confidence_score: response.confidence_score,
          receipt_id: response.retrieval_receipt_id || response.receipt?.receipt_id || 'rcpt-direct',
          sufficient_evidence: response.sufficient_evidence ?? ((response.citations || []).length > 0),
          role_agent: response.role_agent,
          trace: response.trace,
        };

        setMessagesList(prev => [
          ...prev,
          {
            id: assistantId,
            role: 'assistant',
            content: response.answer,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            ...customData,
          }
        ]);
        setActiveMessageId(assistantId);

        return {
          content: [
            {
              type: 'text',
              text: response.answer,
            },
          ],
          metadata: {
            custom: customData,
          },
        };
      } catch (err: any) {
        if (err instanceof ApiError && err.status === 401) {
          if (onUnauthorized) onUnauthorized();
          throw err;
        }

        const errorMsgId = `error-${Date.now()}`;
        const errorContent = err.message || 'No authorized evidence was found.';
        const customData = {
          citations: [],
          confidence_score: 0,
          sufficient_evidence: false,
          receipt_id: 'rcpt-error',
        };

        setMessagesList(prev => [
          ...prev,
          {
            id: errorMsgId,
            role: 'assistant',
            content: errorContent,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            ...customData,
          }
        ]);
        setActiveMessageId(errorMsgId);

        return {
          content: [
            {
              type: 'text',
              text: errorContent,
            },
          ],
          metadata: {
            custom: customData,
          },
        };
      } finally {
        setLoading(false);
      }
    },
  };

  const runtime = useLocalRuntime(adapter);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messagesList, loading]);

  useEffect(() => {
    if (onSelectPromptQuery) {
      handleSendMessage(onSelectPromptQuery);
      if (onClearSelectedPrompt) onClearSelectedPrompt();
    }
  }, [onSelectPromptQuery]);

  const handleSendMessage = (textToSend: string) => {
    if (!textToSend.trim() || loading) return;
    const userMsgId = `user-${Date.now()}`;
    setMessagesList(prev => [
      ...prev,
      {
        id: userMsgId,
        role: 'user',
        content: textToSend.trim(),
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }
    ]);
    setLoading(true);
    runtime.thread.append({
      role: 'user',
      content: [{ type: 'text', text: textToSend.trim() }],
    });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;
    handleSendMessage(input);
    setInput('');
  };

  const activeMessage = messagesList.find(m => m.id === activeMessageId) || 
    messagesList.slice().reverse().find(m => m.role === 'assistant');

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="flex-1 flex flex-col lg:flex-row h-[calc(100vh-3rem)] bg-[#0a0a0a] text-neutral-200 overflow-hidden font-sans">
        {/* Main Chat Stream */}
        <div className="flex-1 flex flex-col h-full overflow-hidden bg-[#0a0a0a]">
          {/* Message Stream */}
          <div className="flex-1 overflow-y-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
            {messagesList.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center max-w-lg mx-auto py-12 relative">
                {/* Light ASCII background texture for empty chat state */}
                <div className="absolute inset-0 flex items-center justify-center opacity-10 pointer-events-none">
                  <AsciiArt className="w-full h-full object-cover" />
                </div>

                <div className="relative z-10 space-y-3 font-mono">
                  <div className="text-xs text-neutral-500 uppercase tracking-widest">
                    Thread // Workspace Context Core
                  </div>
                  <h3 className="text-base font-bold text-neutral-100">
                    Search retrieves. Memory stores. Thread reconstructs.
                  </h3>
                  <p className="text-xs text-neutral-400 font-sans leading-relaxed max-w-md mx-auto">
                    Query organizational context across Discord, Slack, Telegram, and GitHub in {workspaceName} with pre-retrieval security.
                  </p>
                </div>
              </div>
            ) : (
              messagesList.map((msg) => (
                <div
                  key={msg.id}
                  onClick={() => msg.role === 'assistant' && setActiveMessageId(msg.id)}
                  className={`max-w-3xl mx-auto w-full border-b border-neutral-900 pb-6 transition-colors ${
                    msg.role === 'user' ? 'text-right' : 'text-left'
                  }`}
                >
                  {msg.role === 'user' ? (
                    <div className="inline-block text-right space-y-1">
                      <div className="font-mono text-[10px] text-neutral-500 uppercase">
                        // user &bull; {msg.timestamp}
                      </div>
                      <div className="text-xs font-mono text-neutral-100 bg-neutral-900/80 px-3.5 py-2.5 rounded-md border border-neutral-800 leading-relaxed inline-block text-left">
                        {msg.content}
                      </div>
                    </div>
                  ) : (
                    /* Assistant Message Typographic Block */
                    <div className="space-y-2 text-xs font-sans leading-relaxed">
                      {/* Typographic Metadata Header */}
                      <div className="font-mono text-[11px] text-neutral-400 flex items-center justify-between pb-1 border-b border-neutral-900">
                        <span>
                          [{msg.role_agent?.name || 'ThreadAgent'}] &bull; {msg.role_agent?.role || 'Context Agent'}
                        </span>
                        {msg.confidence_score !== undefined && (
                          <span>
                            confidence: {Math.round(msg.confidence_score * 100)}%
                          </span>
                        )}
                      </div>

                      {/* Content Answer */}
                      <div className="text-xs text-neutral-200 whitespace-pre-line pt-1">
                        {msg.content}
                      </div>

                      {/* Insufficient Evidence Warning Banner */}
                      {msg.sufficient_evidence === false && (
                        <div className="p-2.5 border border-amber-900/80 bg-amber-950/20 text-amber-300 font-mono text-[11px] mt-2">
                          [warning] No authorized evidence was found.
                        </div>
                      )}

                      {/* Citations Inspector Link */}
                      {msg.citations && msg.citations.length > 0 && (
                        <div className="pt-2 flex items-center justify-between font-mono text-[10px] text-neutral-500">
                          <span>citations: {msg.citations.length} records</span>
                          <button
                            onClick={() => {
                              setActiveMessageId(msg.id);
                              setIsMobileEvidenceOpen(true);
                            }}
                            className="text-neutral-300 hover:text-white underline cursor-pointer"
                          >
                            inspect evidence &rarr;
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))
            )}

            {loading && (
              <div className="max-w-3xl mx-auto font-mono text-xs text-neutral-400 flex items-center gap-2 py-2">
                <span className="animate-pulse">&gt;</span>
                <span>Reconstructing context across memory core...</span>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input Area: Rectangular, dark surface, thin border, icon-only send action */}
          <div className="border-t border-neutral-800 bg-[#0a0a0a] p-4">
            <div className="max-w-3xl mx-auto">
              <form onSubmit={handleSubmit} className="relative flex items-center">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={`Reconstruct context in ${workspaceName}...`}
                  disabled={loading}
                  className="w-full bg-[#121212] border border-neutral-800 focus:border-neutral-500 focus:outline-hidden rounded-md px-3.5 py-2.5 text-xs text-neutral-100 placeholder:text-neutral-500 font-mono transition-colors disabled:opacity-50"
                />
                <button
                  type="submit"
                  disabled={!input.trim() || loading}
                  title="Send inquiry"
                  className="absolute right-2 p-1.5 rounded-md bg-neutral-800 hover:bg-neutral-700 text-neutral-200 disabled:opacity-30 transition-colors cursor-pointer"
                >
                  <Send className="w-3.5 h-3.5" />
                </button>
              </form>

              <div className="flex items-center justify-between font-mono text-[10px] text-neutral-500 mt-2 px-1">
                <span>Pre-retrieval security boundary active</span>
                <button
                  onClick={() => setIsMobileEvidenceOpen(true)}
                  className="lg:hidden text-neutral-300 underline"
                >
                  view inspector
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Evidence Inspector Rail */}
        <EvidenceRail
          citations={activeMessage?.citations || []}
          confidenceScore={activeMessage?.confidence_score}
          receiptId={activeMessage?.receipt_id}
          sufficientEvidence={activeMessage?.sufficient_evidence}
          isOpenMobile={isMobileEvidenceOpen}
          onCloseMobile={() => setIsMobileEvidenceOpen(false)}
        />
      </div>
    </AssistantRuntimeProvider>
  );
};
