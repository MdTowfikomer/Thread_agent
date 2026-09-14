import React, { useState, useRef, useEffect } from 'react';
import { ChatMessage, UserRole } from '../types';
import { 
  Send, Bot, User, Sparkles, CheckCircle2, ChevronRight, 
  ExternalLink, FileText, Database, GitBranch, ShieldCheck
} from 'lucide-react';

interface ChatAreaProps {
  messages: ChatMessage[];
  loading: boolean;
  onSendMessage: (query: string) => void;
  workspaceName: string;
  userRole: UserRole;
}

export const ChatArea: React.FC<ChatAreaProps> = ({
  messages,
  loading,
  onSendMessage,
  workspaceName,
  userRole
}) => {
  const [input, setInput] = useState('');
  const [expandedCitations, setExpandedCitations] = useState<Record<string, boolean>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;
    onSendMessage(input.trim());
    setInput('');
  };

  const toggleCitations = (msgId: string) => {
    setExpandedCitations(prev => ({ ...prev, [msgId]: !prev[msgId] }));
  };

  const getSourceIcon = (source: string) => {
    switch (source?.toLowerCase()) {
      case 'github':
        return <GitBranch className="w-3.5 h-3.5 text-purple-400" />;
      case 'gdrive':
        return <FileText className="w-3.5 h-3.5 text-emerald-400" />;
      case 'discord':
      case 'slack':
        return <Database className="w-3.5 h-3.5 text-blue-400" />;
      default:
        return <FileText className="w-3.5 h-3.5 text-amber-400" />;
    }
  };

  return (
    <div className="flex-1 flex flex-col h-[calc(100vh-4rem)] bg-slate-950">
      {/* Messages Scroll Area */}
      <div className="flex-1 overflow-y-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center max-w-lg mx-auto py-12">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-tr from-indigo-500/20 to-blue-500/20 border border-indigo-500/30 flex items-center justify-center mb-4 shadow-xl">
              <Bot className="w-8 h-8 text-indigo-400" />
            </div>
            <h3 className="text-xl font-extrabold text-white mb-1 tracking-tight">
              Thread Organizational Context Agent
            </h3>
            <p className="text-xs text-indigo-400 font-semibold mb-3">
              Search retrieves. Memory stores. Thread reconstructs.
            </p>
            <p className="text-xs text-slate-400 leading-relaxed mb-6">
              Access the scattered knowledge across {workspaceName}—reconstructing the decisions, code, conversations, and people behind the work.
            </p>

            <div className="p-4 rounded-2xl bg-slate-900/80 border border-slate-800 text-left w-full text-xs text-slate-300 space-y-2 shadow-lg">
              <div className="flex items-center gap-1.5 text-indigo-400 font-semibold">
                <Sparkles className="w-3.5 h-3.5" />
                <span>Context Reconstruction Pipeline:</span>
              </div>
              <p className="text-slate-400 text-[11px] leading-relaxed">
                <strong>Identity & Pre-Retrieval ACL</strong> $\rightarrow$ <strong>Triage Router</strong> $\rightarrow$ <strong>Role Agent</strong> $\rightarrow$ <strong>Peer Consultation</strong> $\rightarrow$ <strong>Evidence Verification</strong> $\rightarrow$ <strong>Synthesis</strong>.
              </p>
            </div>
          </div>
        ) : (
          messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'} max-w-4xl mx-auto w-full`}
            >
              {/* User Message */}
              {msg.role === 'user' ? (
                <div className="flex items-start gap-2.5 max-w-[85%]">
                  <div className="bg-gradient-to-r from-blue-600 to-indigo-600 text-white rounded-2xl rounded-tr-none px-4 py-3 shadow-md shadow-indigo-500/10">
                    <p className="text-sm leading-relaxed">{msg.content}</p>
                    <span className="text-[10px] text-blue-200/70 mt-1 block text-right">
                      {msg.timestamp}
                    </span>
                  </div>
                  <div className="w-8 h-8 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center shrink-0">
                    <User className="w-4 h-4 text-slate-300" />
                  </div>
                </div>
              ) : (
                /* Assistant Message */
                <div className="flex items-start gap-3 max-w-[95%] w-full">
                  <img
                    src={msg.role_agent?.avatar || 'https://api.dicebear.com/7.x/bottts/svg?seed=thread'}
                    alt={msg.role_agent?.name}
                    className="w-9 h-9 rounded-xl bg-slate-900 ring-1 ring-slate-700 shrink-0 mt-1"
                  />

                  <div className="flex-1 bg-slate-900/90 border border-slate-800/90 rounded-2xl rounded-tl-none p-5 shadow-xl space-y-4">
                    {/* Header: Role Agent info & confidence */}
                    <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-sm text-slate-100">
                            {msg.role_agent?.name}
                          </span>
                          <span className="text-[11px] font-semibold px-2 py-0.5 rounded-md bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                            {msg.role_agent?.role}
                          </span>
                        </div>
                        <span className="text-[10px] text-slate-400">
                          {msg.role_agent?.department}
                        </span>
                      </div>

                      {msg.confidence_score !== undefined && (
                        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold">
                          <CheckCircle2 className="w-3.5 h-3.5" />
                          <span>{Math.round(msg.confidence_score * 100)}% Confidence</span>
                        </div>
                      )}
                    </div>

                    {/* Agent Trace Stepper */}
                    {msg.trace && msg.trace.length > 0 && (
                      <div className="p-2.5 rounded-xl bg-slate-950/60 border border-slate-800/80 text-xs space-y-1.5">
                        <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider flex items-center gap-1.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400"></span>
                          LangGraph Execution Pipeline
                        </span>
                        <div className="flex flex-col gap-1">
                          {msg.trace.map((step, sIdx) => (
                            <div key={sIdx} className="flex items-start gap-2 text-[11px]">
                              <span className="font-semibold text-slate-300 shrink-0">
                                [{step.step}]:
                              </span>
                              <span className="text-slate-400">
                                {step.message}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Content Answer */}
                    <div className="text-sm text-slate-200 leading-relaxed whitespace-pre-line font-normal">
                      {msg.content}
                    </div>

                    {/* Citations Accordion */}
                    {msg.citations && msg.citations.length > 0 && (
                      <div className="border-t border-slate-800/80 pt-3">
                        <button
                          onClick={() => toggleCitations(msg.id)}
                          className="flex items-center justify-between w-full text-xs font-semibold text-slate-300 hover:text-indigo-400 transition-colors py-1 cursor-pointer"
                        >
                          <div className="flex items-center gap-1.5">
                            <span className="w-2 h-2 rounded-full bg-indigo-500"></span>
                            <span>Verified Canonical Sources ({msg.citations.length})</span>
                          </div>
                          <span className="text-[11px] text-slate-400">
                            {expandedCitations[msg.id] ? 'Hide Sources' : 'Inspect Sources'}
                          </span>
                        </button>

                        {expandedCitations[msg.id] && (
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-2.5 pt-1">
                            {msg.citations.map((c, cIdx) => (
                              <div
                                key={cIdx}
                                className="p-3 rounded-xl bg-slate-950/70 border border-slate-800/90 flex flex-col justify-between gap-2"
                              >
                                <div>
                                  <div className="flex items-center justify-between mb-1.5">
                                    <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-200 truncate">
                                      {getSourceIcon(c.source)}
                                      <span className="truncate">{c.title || 'Institutional Record'}</span>
                                    </div>
                                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">
                                      {Math.round(c.relevance_score * 100)}% match
                                    </span>
                                  </div>
                                  <p className="text-[11px] text-slate-400 leading-relaxed line-clamp-3">
                                    "{c.snippet}"
                                  </p>
                                </div>

                                <div className="flex items-center justify-between pt-1 border-t border-slate-800/60 text-[10px] text-slate-500">
                                  <span>Author: {c.author}</span>
                                  {c.source_uri ? (
                                    <a
                                      href={c.source_uri}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="flex items-center gap-1 text-indigo-400 hover:text-indigo-300"
                                    >
                                      <span>Source</span>
                                      <ExternalLink className="w-2.5 h-2.5" />
                                    </a>
                                  ) : (
                                    <span className="capitalize">{c.source}</span>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))
        )}

        {/* Loading indicator */}
        {loading && (
          <div className="flex items-center gap-3 max-w-4xl mx-auto w-full">
            <div className="w-9 h-9 rounded-xl bg-indigo-950/80 border border-indigo-500/30 flex items-center justify-center animate-pulse">
              <Bot className="w-5 h-5 text-indigo-400" />
            </div>
            <div className="p-4 rounded-2xl bg-slate-900 border border-slate-800 text-xs text-slate-300 flex items-center gap-2 shadow-lg">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
              </span>
              <span>Reconstructing context across role agents and canonical memory...</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="border-t border-slate-800/80 bg-slate-950/80 backdrop-blur-md p-4">
        <div className="max-w-4xl mx-auto">
          <form onSubmit={handleSubmit} className="relative flex items-center">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={`Ask Thread to reconstruct context in ${workspaceName}...`}
              disabled={loading}
              className="w-full bg-slate-900 border border-slate-800 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/50 rounded-2xl pl-4 pr-12 py-3.5 text-sm text-slate-100 placeholder:text-slate-500 outline-none transition-all disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!input.trim() || loading}
              className="absolute right-2.5 p-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 disabled:hover:bg-indigo-600 transition-all shadow-md shadow-indigo-600/30 cursor-pointer"
            >
              <Send className="w-4 h-4" />
            </button>
          </form>

          <div className="flex items-center justify-between text-[11px] text-slate-500 mt-2 px-1">
            <span className="flex items-center gap-1.5">
              <ShieldCheck className="w-3.5 h-3.5 text-indigo-400" />
              <span>
                Authenticated as <strong>{userRole === 'organizer' ? 'Organizer Core' : 'Community Member'}</strong>
              </span>
            </span>
            <span className="flex items-center gap-1">
              Press <kbd className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-[10px] font-mono">Enter</kbd> to query
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
