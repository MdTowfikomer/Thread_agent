import React from 'react';
import { ArrowRight, Terminal } from 'lucide-react';
import { AsciiArt } from '@/components/ui/minimal-2';

interface LandingPageProps {
  onOpenWorkspace: () => void;
}

export const LandingPage: React.FC<LandingPageProps> = ({ onOpenWorkspace }) => {
  return (
    <div className="min-h-screen bg-[#0a0a0a] text-neutral-200 flex flex-col font-sans relative overflow-hidden">
      {/* 21st Minimal-2 Full-Bleed AsciiArt Hero Background */}
      <div className="absolute inset-0 z-0 flex items-center justify-center opacity-30 pointer-events-none overflow-hidden">
        <AsciiArt className="w-full h-full object-cover" />
      </div>

      {/* Top Hairline Header */}
      <header className="relative z-10 border-b border-neutral-800/80 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-neutral-400" />
          <span className="font-mono text-xs font-bold uppercase tracking-widest text-neutral-100">
            THREAD
          </span>
        </div>

        <button
          onClick={onOpenWorkspace}
          className="text-xs font-mono text-neutral-400 hover:text-neutral-100 transition-colors cursor-pointer flex items-center gap-1.5"
        >
          <span>Open workspace</span>
          <ArrowRight className="w-3.5 h-3.5" />
        </button>
      </header>

      {/* Full-Bleed Minimal Hero Section */}
      <main className="relative z-10 flex-1 max-w-4xl mx-auto px-6 py-20 md:py-32 flex flex-col items-start justify-center">
        {/* Wordmark */}
        <div className="font-mono text-xs text-neutral-500 uppercase tracking-widest mb-4">
          Thread / Memory Core
        </div>

        {/* Minimal Title */}
        <h1 className="text-3xl sm:text-5xl font-mono font-bold text-neutral-100 tracking-tight leading-tight">
          THREAD
        </h1>

        {/* One Concise Sentence */}
        <p className="mt-4 text-base sm:text-lg text-neutral-400 font-normal max-w-xl leading-relaxed font-sans">
          Permission-aware organizational memory across Discord, Slack, Telegram, and GitHub.
        </p>

        {/* Understated Text-Link Action */}
        <div className="mt-8 flex items-center gap-4">
          <button
            onClick={onOpenWorkspace}
            className="inline-flex items-center gap-2 text-sm font-mono text-neutral-100 hover:text-white transition-colors cursor-pointer group underline decoration-neutral-700 underline-offset-4"
          >
            <span>Open workspace</span>
            <ArrowRight className="w-4 h-4 text-neutral-400 group-hover:translate-x-0.5 transition-transform" />
          </button>
        </div>

        {/* Hairline Operational Preview Wireframe */}
        <div className="mt-16 w-full border-t border-neutral-800 pt-8 font-mono text-xs space-y-4">
          <div className="flex items-center justify-between text-neutral-500 text-[11px] pb-2 border-b border-neutral-900">
            <span>// ARCHITECTURE_SPEC</span>
            <span>ACL_BOUNDARIES: PRE-RETRIEVAL</span>
          </div>

          <div className="grid sm:grid-cols-3 gap-6 text-[11px] text-neutral-400">
            <div>
              <span className="text-neutral-200 font-bold block mb-1">01. INGESTION</span>
              <p className="text-neutral-500 leading-snug font-sans">Discord gateway worker, Slack events, Telegram webhooks, signed GitHub commits.</p>
            </div>
            <div>
              <span className="text-neutral-200 font-bold block mb-1">02. MEMORY CORE</span>
              <p className="text-neutral-500 leading-snug font-sans">Vector RRF search with Supabase pgvector and PostgreSQL advisory locks.</p>
            </div>
            <div>
              <span className="text-neutral-200 font-bold block mb-1">03. RECONSTRUCTION</span>
              <p className="text-neutral-500 leading-snug font-sans">Deterministic role triage and grounded evidence synthesis with receipts.</p>
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="relative z-10 border-t border-neutral-900 px-6 py-4 text-left font-mono text-[11px] text-neutral-600">
        Thread Operational UI — Powered by 21st.dev Minimal-2 ASCII hero.
      </footer>
    </div>
  );
};
