import React from 'react';
import { Citation } from '../types';
import { ExternalLink, X } from 'lucide-react';

interface EvidenceRailProps {
  citations: Citation[];
  confidenceScore?: number;
  receiptId?: string;
  sufficientEvidence?: boolean;
  isOpenMobile: boolean;
  onCloseMobile: () => void;
}

export const EvidenceRail: React.FC<EvidenceRailProps> = ({
  citations = [],
  confidenceScore,
  receiptId,
  sufficientEvidence = true,
  isOpenMobile,
  onCloseMobile,
}) => {
  const content = (
    <div className="space-y-6 text-xs text-neutral-300 font-mono">
      {/* Inspector Header */}
      <div className="pb-3 border-b border-neutral-800 flex items-center justify-between">
        <div>
          <h3 className="font-bold text-xs uppercase tracking-wider text-neutral-100">
            // Evidence Inspector
          </h3>
          <p className="text-[10px] text-neutral-500 mt-0.5 font-sans">
            Pre-retrieval ACL & Retrieval Ledger Audit
          </p>
        </div>
        <button
          onClick={onCloseMobile}
          className="lg:hidden p-1 text-neutral-500 hover:text-neutral-200 cursor-pointer"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Functional Warning State if Insufficient Evidence */}
      {sufficientEvidence === false && (
        <div className="p-3 border border-amber-800/80 bg-amber-950/20 text-amber-300 text-[11px] font-sans space-y-1">
          <span className="font-bold block uppercase tracking-wider font-mono text-[10px]">
            [Warning] Insufficient Evidence
          </span>
          <p className="leading-relaxed">
            No authorized evidence was found within your verified security level matching this inquiry.
          </p>
        </div>
      )}

      {/* Metrics Metadata Table */}
      <div className="border border-neutral-800 p-3 space-y-2 text-[11px] bg-neutral-950">
        <div className="flex justify-between">
          <span className="text-neutral-500">Confidence:</span>
          <span className="text-neutral-200 font-bold">
            {confidenceScore !== undefined ? `${Math.round(confidenceScore * 100)}%` : 'N/A'}
          </span>
        </div>
        <div className="flex justify-between border-t border-neutral-900 pt-1">
          <span className="text-neutral-500">Receipt ID:</span>
          <span className="text-neutral-200 font-bold truncate max-w-[140px]">
            {receiptId || 'rcpt-direct'}
          </span>
        </div>
        <div className="flex justify-between border-t border-neutral-900 pt-1">
          <span className="text-neutral-500">ACL Boundary:</span>
          <span className="text-neutral-200 font-bold">Pre-Retrieval Enforced</span>
        </div>
      </div>

      {/* Canonical Citations List */}
      <div>
        <div className="text-[10px] uppercase text-neutral-500 tracking-wider mb-3">
          // Canonical Citations ({citations.length})
        </div>

        {citations.length === 0 ? (
          <div className="p-4 border border-neutral-800 text-neutral-500 text-center text-[11px] font-sans">
            No active citations for this response.
          </div>
        ) : (
          <div className="space-y-4 max-h-[calc(100vh-22rem)] overflow-y-auto pr-1">
            {citations.map((c, idx) => (
              <article
                key={c.item_id || idx}
                className="pb-3 border-b border-neutral-800 space-y-1.5 text-[11px]"
              >
                <div className="flex items-center justify-between font-bold text-neutral-100">
                  <span className="truncate">[{c.source?.toUpperCase()}] {c.title || 'Record'}</span>
                  <span className="text-[10px] text-neutral-500 font-normal">
                    {Math.round((c.relevance_score || 0) * 100)}%
                  </span>
                </div>

                <p className="text-neutral-400 font-sans text-xs leading-relaxed italic">
                  "{c.snippet}"
                </p>

                <div className="flex items-center justify-between text-[10px] text-neutral-500 pt-1">
                  <span>Author: {c.author}</span>
                  <span>Scope: {c.permission}</span>
                </div>

                {c.source_uri && (
                  <div className="text-right pt-0.5">
                    <a
                      href={c.source_uri}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-[10px] text-neutral-300 hover:text-white underline decoration-neutral-700"
                    >
                      <span>source</span>
                      <ExternalLink className="w-2.5 h-2.5" />
                    </a>
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop Persistent Inspector Panel */}
      <aside className="w-80 border-l border-neutral-800 bg-[#0a0a0a] p-4 shrink-0 hidden lg:block overflow-y-auto">
        {content}
      </aside>

      {/* Mobile Drawer */}
      {isOpenMobile && (
        <div className="fixed inset-0 z-50 lg:hidden flex flex-col justify-end bg-black/70 backdrop-blur-xs">
          <div className="bg-[#0a0a0a] border-t border-neutral-800 p-5 max-h-[80vh] overflow-y-auto shadow-2xl">
            {content}
          </div>
        </div>
      )}
    </>
  );
};
