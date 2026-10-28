import React, { useState } from 'react';
import { Check, ChevronDown, ChevronRight, Terminal, Wrench, Search, Cpu, Sparkles } from 'lucide-react';
import { ToolCallStep } from '../types';

interface ToolTimelineProps {
  stages: ToolCallStep[];
  isPending?: boolean;
  defaultExpanded?: boolean;
}

function getStepIcon(step: ToolCallStep) {
  if (step.tool) return <Wrench className="h-3 w-3 text-neutral-400" />;
  if (step.step === 'triage_router') return <Cpu className="h-3 w-3 text-neutral-400" />;
  if (step.step === 'retrieval_service') return <Search className="h-3 w-3 text-neutral-400" />;
  if (step.step === 'synthesis') return <Sparkles className="h-3 w-3 text-neutral-400" />;
  return <Terminal className="h-3 w-3 text-neutral-400" />;
}

export const ToolTimeline: React.FC<ToolTimelineProps> = ({
  stages,
  isPending = false,
  defaultExpanded,
}) => {
  const hasTool = stages.some((s) => Boolean(s.tool));
  const [isExpanded, setIsExpanded] = useState<boolean>(
    defaultExpanded !== undefined ? defaultExpanded : (isPending || hasTool)
  );

  if (!stages || stages.length === 0) return null;

  const toolStep = stages.find((s) => Boolean(s.tool));
  const summaryTitle = toolStep
    ? `Tool: ${toolStep.tool}`
    : stages.some((s) => s.count !== undefined && s.count > 0)
    ? `Retrieved ${stages.find((s) => s.count !== undefined)?.count} records`
    : `${stages.length} workflow steps`;

  return (
    <div className="my-2.5 overflow-hidden rounded-md border border-neutral-800 bg-[#0a0a0a]">
      {/* Header bar / Timeline Toggle */}
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex w-full cursor-pointer select-none items-center justify-between bg-[#0a0a0a] px-3 py-2 text-left transition-colors hover:bg-neutral-900/40"
        aria-expanded={isExpanded}
      >
        <div className="flex items-center gap-2">
          <Terminal className="h-3.5 w-3.5 text-neutral-400" />
          <span className="font-mono text-xs font-medium text-neutral-200">
            {summaryTitle}
          </span>
          {isPending && (
            <span className="flex items-center gap-1.5 font-mono text-[10px] text-neutral-400 uppercase tracking-wider">
              <span className="h-1.5 w-1.5 rounded-full bg-neutral-300 animate-pulse" />
              running
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-neutral-500">
          <span className="font-mono text-[11px] text-neutral-500">
            {stages.length} step{stages.length === 1 ? '' : 's'}
          </span>
          {isExpanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-neutral-400" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-neutral-400" />
          )}
        </div>
      </button>

      {/* Connected Vertical Timeline */}
      {isExpanded && (
        <div className="border-t border-neutral-800 bg-[#0a0a0a] px-4 py-3">
          <div className="relative pl-6 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-px before:bg-neutral-800">
            <div className="space-y-3">
              {stages.map((step, idx) => {
                const isStepRunning = step.status === 'running';
                const isStepFailed = step.status === 'failed';
                const isStepCompleted = step.status === 'completed';

                return (
                  <div key={idx} className="relative flex flex-col gap-0.5">
                    {/* Timeline Node Dot */}
                    <div className="absolute -left-6 top-0.5 flex h-4 w-4 items-center justify-center bg-[#0a0a0a]">
                      {isStepRunning ? (
                        <span className="relative flex h-2 w-2">
                          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-neutral-400 opacity-75" />
                          <span className="relative inline-flex h-2 w-2 rounded-full bg-neutral-200" />
                        </span>
                      ) : isStepCompleted ? (
                        <div className="grid h-3.5 w-3.5 place-items-center rounded-full border border-neutral-700 bg-[#0a0a0a] text-neutral-300">
                          <Check className="h-2 w-2 stroke-[2.5]" />
                        </div>
                      ) : isStepFailed ? (
                        <div className="h-2 w-2 rounded-full bg-red-400" />
                      ) : (
                        <div className="h-1.5 w-1.5 rounded-full bg-neutral-600" />
                      )}
                    </div>

                    {/* Step Title & Meta */}
                    <div className="flex items-center gap-2">
                      <span className="flex items-center gap-1.5 font-mono text-xs font-medium text-neutral-200">
                        {getStepIcon(step)}
                        {step.tool ? `tool: ${step.tool}` : step.label}
                      </span>
                      <span className="font-mono text-[10px] uppercase tracking-wider text-neutral-500">
                        {step.status}
                      </span>
                    </div>

                    {/* Step Message / Description */}
                    {step.message && (
                      <p className="font-mono text-[11px] leading-relaxed text-neutral-400">
                        {step.message}
                      </p>
                    )}

                    {/* Tool Arguments Block */}
                    {step.toolArgs && (
                      <div className="mt-1 rounded border border-neutral-800 bg-[#0a0a0a] px-2.5 py-1.5 font-mono text-[11px] text-neutral-300">
                        <span className="text-neutral-500">input: </span>
                        <code>{step.toolArgs}</code>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
