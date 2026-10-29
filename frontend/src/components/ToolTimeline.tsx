import { useId, useState } from 'react';
import { Check, ChevronDown, ChevronRight, CircleAlert, LoaderCircle, Search, Sparkles, Wrench } from 'lucide-react';
import { ToolCallStep } from '../types';

interface ToolTimelineProps {
  stages: ToolCallStep[];
  isPending?: boolean;
  defaultExpanded?: boolean;
}

function activityLabel(step?: ToolCallStep) {
  if (!step) return 'Getting started…';
  if (step.tool) return `Using ${step.tool}…`;
  if (step.step === 'finalizing') return 'Finishing your response…';
  if (step.step === 'triage_router') return 'Understanding your question…';
  if (step.step === 'retrieval_service' && step.label !== 'Direct synthesis') return 'Checking records…';
  return 'Preparing an answer…';
}

export function ToolTimeline({ stages, isPending = false, defaultExpanded }: ToolTimelineProps) {
  const id = useId();
  const tools = stages.filter(step => Boolean(step.tool));
  const [expanded, setExpanded] = useState(defaultExpanded ?? (isPending || tools.length > 0));
  const [openRows, setOpenRows] = useState<Set<string>>(new Set());
  const rows = tools.length ? tools : stages.filter(step =>
    step.step === 'synthesis' || (step.step === 'retrieval_service' && step.label !== 'Direct synthesis')
  );
  const running = [...stages].reverse().find(step => step.status === 'running');
  const failed = stages.some(step => step.status === 'failed');
  const heading = tools.length ? `${tools.length} tool call${tools.length === 1 ? '' : 's'}` : 'Response activity';

  if (!stages.length && !isPending) return null;

  return <div className="my-3 text-sm">
    {isPending && <p role="status" className="mb-2 flex items-center gap-2 text-neutral-300">
      <LoaderCircle className="h-3.5 w-3.5 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden="true" />
      {activityLabel(running)}
    </p>}
    {rows.length > 0 && <>
      <button type="button" onClick={() => setExpanded(value => !value)} aria-expanded={expanded} aria-controls={`${id}-activity`}
        className="inline-flex min-h-8 items-center gap-1.5 rounded-sm text-neutral-400 transition-colors hover:text-neutral-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-neutral-400">
        {heading}
        <ChevronDown className={`h-3.5 w-3.5 transition-transform motion-reduce:transition-none ${expanded ? '' : '-rotate-90'}`} aria-hidden="true" />
        {failed && <span className="ml-1 text-red-300">Interrupted</span>}
      </button>
      {expanded && <ul id={`${id}-activity`} aria-label="Execution activity" className="mt-1 space-y-1">
        {rows.map((step, index) => {
          const key = `${step.step}-${step.tool ?? ''}-${index}`;
          const open = openRows.has(key);
          const Icon = step.status === 'failed' ? CircleAlert : step.status === 'running' ? LoaderCircle : step.tool ? Wrench : step.step === 'retrieval_service' ? Search : Sparkles;
          const summary = step.count !== undefined ? `${step.count} record${step.count === 1 ? '' : 's'} checked` : step.toolArgs || (step.status === 'running' ? 'In progress' : step.message || 'Finished');
          return <li key={key}>
            <button type="button" aria-expanded={open} aria-controls={`${id}-row-${index}`} aria-label={`${step.tool || step.label}, ${step.status}`}
              onClick={() => setOpenRows(current => { const next = new Set(current); if (next.has(key)) next.delete(key); else next.add(key); return next; })}
              className="group flex min-h-9 w-full items-start gap-2.5 rounded-sm py-1.5 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-neutral-400">
              <Icon aria-hidden="true" className={`mt-0.5 h-4 w-4 shrink-0 ${step.status === 'failed' ? 'text-red-300' : 'text-neutral-400'} ${step.status === 'running' ? 'animate-spin motion-reduce:animate-none' : ''}`} />
              <span className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className={`${step.tool ? 'font-mono' : ''} text-neutral-300 group-hover:text-neutral-100`}>{step.tool || step.label}</span>
                <span className="min-w-0 break-words text-neutral-400 sm:truncate">{summary}</span>
              </span>
              <ChevronRight aria-hidden="true" className={`mt-0.5 h-3.5 w-3.5 shrink-0 text-neutral-500 transition-transform motion-reduce:transition-none ${open ? 'rotate-90' : ''}`} />
            </button>
            {open && <div id={`${id}-row-${index}`} className="mb-2 ml-6 border-l border-neutral-800 py-1 pl-3 text-xs leading-6 text-neutral-400">
              <p className="flex items-center gap-1.5">{step.status === 'completed' && <Check className="h-3 w-3" aria-hidden="true" />}{step.status === 'completed' ? 'Finished' : step.status === 'failed' ? 'Could not finish' : 'Running'}</p>
              {step.message && <p className="break-words">{step.message}</p>}
              {step.toolArgs && <p className="break-all"><span className="text-neutral-300">Input: </span><code>{step.toolArgs}</code></p>}
            </div>}
          </li>;
        })}
      </ul>}
    </>}
  </div>;
}
