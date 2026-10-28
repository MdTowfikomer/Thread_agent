import React, { useRef, useState } from 'react';
import { ApiError, v2Request } from '../api';

interface TraceStage {
  step: string; status: string; message?: string; latency_ms?: number;
  model_name?: string; input_tokens?: number; output_tokens?: number; is_estimated?: boolean;
  strategy?: string; filtered_count?: number; error_status?: number;
  evidence?: Array<{ item_id: string; title?: string; author?: string; score?: number; source?: string }>;
  scores?: Record<string, Record<string, number | null>>;
}
interface TraceDocument {
  id: string; conversation_id: string; turn_id: string; outcome: string;
  stages: TraceStage[];
  metrics: { total_latency_ms?: number; input_tokens?: number; output_tokens?: number; token_reporting_type?: string };
}
const labels: Record<string, string> = {
  triage_router: 'Intent routing', retrieval_service: 'Evidence retrieval', role_agent_verification: 'Evidence check',
  synthesis: 'Answer generation', model_usage: 'Provider usage', platform_formatter: 'Output formatting',
};

export function TraceInspector({ orgId, traceId }: { orgId: string; traceId: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [trace, setTrace] = useState<TraceDocument | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const open = async () => {
    if (!dialog.current?.open) dialog.current?.showModal();
    setLoading(true); setTrace(null); setError('');
    try { setTrace(await v2Request<TraceDocument>(`/organizations/${encodeURIComponent(orgId)}/traces/${encodeURIComponent(traceId)}`)); }
    catch (e) { setError(e instanceof ApiError && [403, 404].includes(e.status) ? 'This trace is unavailable or you no longer have access.' : e instanceof Error ? e.message : 'The trace could not be loaded.'); }
    finally { setLoading(false); }
  };
  return <>
    <button ref={trigger} type="button" onClick={() => void open()} className="mt-4 min-h-9 text-sm text-neutral-400 underline decoration-neutral-700 underline-offset-4 hover:text-white">Inspect execution</button>
    <dialog ref={dialog} className="v2-dialog max-h-[85svh] max-w-3xl overflow-y-auto" aria-labelledby={`trace-heading-${traceId}`} onClose={() => trigger.current?.focus()}>
      <div className="flex items-center justify-between gap-4"><h2 id={`trace-heading-${traceId}`} className="text-2xl tracking-tight">Execution trace</h2><button className="v2-secondary" onClick={() => dialog.current?.close()}>Close</button></div>
      {loading && <p role="status" className="mt-6 text-sm text-neutral-400">Loading the saved execution…</p>}
      {error && <div className="mt-6 space-y-4"><p role="alert" className="text-sm text-red-300">{error}</p><button className="v2-secondary" onClick={() => void open()}>Retry</button></div>}
      {trace && <>
        <div className="mt-6 flex flex-wrap gap-x-6 gap-y-2 border-y border-neutral-800 py-4 text-sm tabular-nums"><span className="capitalize">{trace.outcome}</span><span>{Math.round(trace.metrics.total_latency_ms ?? 0)} ms total</span><span>{trace.metrics.input_tokens ?? 0} input / {trace.metrics.output_tokens ?? 0} output tokens</span><span className="text-neutral-400">{trace.metrics.token_reporting_type?.replaceAll('_', ' ')}</span></div>
        {trace.outcome === 'running' && <p role="status" className="mt-4 text-sm text-neutral-400">This trace is incomplete. Execution may still be running or finalization may have failed.</p>}
        <ol className="mt-5 divide-y divide-neutral-800">{trace.stages.map((stage, index) => <li key={index} className="py-4">
          <details open={stage.status === 'failed'}><summary className="cursor-pointer text-sm"><span className="font-medium">{labels[stage.step] || stage.step}</span><span className="ml-3 text-neutral-400">{stage.status} · {Math.round(stage.latency_ms ?? 0)} ms</span></summary>
            <div className="mt-3 space-y-3 text-sm text-neutral-400"><p>{stage.message}</p>
              {stage.strategy && <p>Retrieval: {stage.strategy}</p>}
              {stage.filtered_count !== undefined && <p>{stage.filtered_count} candidates excluded by access scope.</p>}
              {stage.error_status && <p>Service status: {stage.error_status}. Check workspace settings and service availability.</p>}
              {stage.model_name && <p className="tabular-nums">{stage.model_name} · {stage.input_tokens ?? 0} input / {stage.output_tokens ?? 0} output tokens · {stage.is_estimated ? 'Estimated' : 'Provider-reported'}</p>}
              {!!stage.evidence?.length && <div className="overflow-x-auto"><table className="w-full text-left text-xs"><caption className="mb-2 text-left">Authorized evidence and available scores</caption><thead><tr><th className="py-2 pr-3">Source</th><th className="pr-3">Dense</th><th className="pr-3">Lexical</th><th>RRF / selected score</th></tr></thead><tbody>{stage.evidence.map(item => { const scores = stage.scores?.[item.item_id]; return <tr key={item.item_id} className="border-t border-neutral-800"><td className="max-w-64 py-3 pr-3">{item.title || item.item_id}<span className="mt-1 block text-neutral-500">{item.source} · {item.author}</span></td><td className="pr-3 tabular-nums">{scores?.dense_similarity?.toFixed(4) ?? 'Unavailable'}</td><td className="pr-3 tabular-nums">{scores?.lexical_score?.toFixed(4) ?? 'Unavailable'}</td><td className="tabular-nums">{(scores?.rrf_score ?? item.score)?.toFixed(4) ?? 'Unavailable'}</td></tr>; })}</tbody></table></div>}
            </div>
          </details>
        </li>)}</ol>
        <details className="mt-5 border-t border-neutral-800 pt-4 text-xs text-neutral-500"><summary className="cursor-pointer">Execution identifiers</summary><dl className="mt-3 space-y-2 break-all"><dt>Trace</dt><dd>{trace.id}</dd><dt>Conversation</dt><dd>{trace.conversation_id}</dd><dt>Turn</dt><dd>{trace.turn_id}</dd></dl></details>
      </>}
    </dialog>
  </>;
}
