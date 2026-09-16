import React from 'react';
import { ExternalLink, FileText, X } from 'lucide-react';
import { Citation } from '../types';

interface EvidenceRailProps {
  citations: Citation[];
  confidenceScore?: number;
  receiptId?: string;
  sufficientEvidence?: boolean;
  isOpenMobile: boolean;
  onCloseMobile: () => void;
  hasActiveResponse: boolean;
}

export const EvidenceRail: React.FC<EvidenceRailProps> = ({
  citations = [],
  confidenceScore,
  receiptId,
  sufficientEvidence = true,
  isOpenMobile,
  onCloseMobile,
  hasActiveResponse,
}) => {
  const content = (
    <div className="text-sm text-neutral-300">
      <div className="flex items-start justify-between border-b border-neutral-800 pb-5">
        <div>
          <p className="text-sm text-neutral-500">Sources</p>
          <h3 className="mt-1 text-lg font-medium text-neutral-100">Evidence</h3>
        </div>
        <button onClick={onCloseMobile} className="text-neutral-500 transition-colors hover:text-neutral-100 lg:hidden" title="Close evidence">
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      {!hasActiveResponse ? (
        <p className="py-6 leading-6 text-neutral-500">Ask Thread a question to inspect the records supporting its response.</p>
      ) : sufficientEvidence === false ? (
        <div className="border-l border-neutral-600 py-5 pl-4 text-sm leading-6 text-neutral-400">
          No authorized evidence was available for this question. Thread has not treated an unsupported claim as a fact.
        </div>
      ) : (
        <div className="divide-y divide-neutral-800">
          {citations.map((citation, index) => (
            <article key={citation.item_id || index} className="py-5">
              <div className="flex items-start justify-between gap-3">
                <span className="text-sm font-medium text-neutral-100">{citation.title || 'Community record'}</span>
                <span className="shrink-0 text-xs text-neutral-500">{citation.source}</span>
              </div>
              <p className="mt-3 text-sm leading-6 text-neutral-400">{citation.snippet}</p>
              <div className="mt-4 flex items-center justify-between gap-3 text-xs text-neutral-500">
                <span className="truncate">{citation.author}</span>
                {citation.source_uri && (
                  <a href={citation.source_uri} target="_blank" rel="noreferrer" className="inline-flex shrink-0 items-center gap-1 text-neutral-300 transition-colors hover:text-white">
                    Open source
                    <ExternalLink className="h-3 w-3" aria-hidden="true" />
                  </a>
                )}
              </div>
            </article>
          ))}
        </div>
      )}

      {hasActiveResponse && (
        <div className="mt-2 border-t border-neutral-800 pt-5 text-xs text-neutral-500">
          <div className="flex items-center gap-2">
            <FileText className="h-3.5 w-3.5" aria-hidden="true" />
            Receipt {receiptId || 'available'}
          </div>
          {confidenceScore !== undefined && <p className="mt-2">Evidence confidence {Math.round(confidenceScore * 100)}%</p>}
        </div>
      )}
    </div>
  );

  return (
    <>
      <aside className="hidden h-full w-80 shrink-0 overflow-y-auto border-l border-neutral-800 bg-[#0a0a0a] p-6 xl:block">{content}</aside>
      {isOpenMobile && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/70 xl:hidden">
          <aside className="h-full w-full max-w-sm overflow-y-auto border-l border-neutral-800 bg-[#0a0a0a] p-6">{content}</aside>
        </div>
      )}
    </>
  );
};
