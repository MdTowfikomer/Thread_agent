import React from 'react';
import { OrganizationWorkspace } from '../types';

interface SidebarProps {
  workspace: OrganizationWorkspace | null;
  onSelectPrompt: (prompt: string) => void;
  activeSourceFilter: string;
  onSelectSourceFilter: (source: string) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  workspace,
  onSelectPrompt,
  activeSourceFilter,
  onSelectSourceFilter,
}) => {
  if (!workspace) return null;

  const samplePrompts = [
    {
      title: "DevFest Venue Approval",
      text: "Where is DevFest taking place and has it been approved?",
      source: "discord"
    },
    {
      title: "GenAI Workshop Setup",
      text: "What are the prerequisites for the GenAI workshop and where is the repo?",
      source: "github"
    },
    {
      title: "Swag & Catering Budget",
      text: "What is our internal budget for attendee t-shirts and swag?",
      source: "slack"
    },
    {
      title: "RSVP & Participation Rules",
      text: "How do community members register and what are certificate criteria?",
      source: "telegram"
    }
  ];

  const sourceFilters = [
    { id: 'all', label: 'all' },
    { id: 'discord', label: 'discord' },
    { id: 'slack', label: 'slack' },
    { id: 'telegram', label: 'telegram' },
    { id: 'github', label: 'github' },
  ];

  return (
    <aside className="w-72 border-r border-neutral-800 bg-[#0a0a0a] p-4 flex flex-col gap-6 overflow-y-auto shrink-0 hidden lg:flex font-mono text-xs">
      {/* Workspace Summary */}
      <div className="pb-3 border-b border-neutral-900">
        <div className="text-[10px] uppercase text-neutral-500 tracking-wider mb-1">
          // Workspace
        </div>
        <div className="font-bold text-neutral-100 text-sm">
          {workspace.name}
        </div>
        <p className="text-[11px] text-neutral-500 mt-1 leading-normal font-sans">
          {workspace.description}
        </p>
      </div>

      {/* Source Scope Filter */}
      <div>
        <div className="text-[10px] uppercase text-neutral-500 tracking-wider mb-2">
          // Source Filter
        </div>
        <div className="flex flex-col gap-1">
          {sourceFilters.map(f => {
            const isActive = activeSourceFilter === f.id;
            return (
              <button
                key={f.id}
                onClick={() => onSelectSourceFilter(f.id)}
                className={`text-left px-2 py-1 text-[11px] font-mono transition-colors cursor-pointer flex items-center justify-between ${
                  isActive
                    ? 'text-neutral-100 font-bold border-l-2 border-neutral-200 bg-neutral-900/60 pl-2.5'
                    : 'text-neutral-400 hover:text-neutral-200'
                }`}
              >
                <span>{f.label}</span>
                {isActive && <span className="text-[9px] text-neutral-500">&bull;</span>}
              </button>
            );
          })}
        </div>
      </div>

      {/* Sample Context Reconstruction Prompts */}
      <div>
        <div className="text-[10px] uppercase text-neutral-500 tracking-wider mb-2">
          // Inquiries
        </div>
        <div className="flex flex-col gap-2">
          {samplePrompts.map((p, idx) => (
            <button
              key={idx}
              onClick={() => onSelectPrompt(p.text)}
              className="text-left p-2.5 border-l border-neutral-800 hover:border-neutral-400 transition-colors group cursor-pointer"
            >
              <div className="flex items-center justify-between text-[11px] mb-1">
                <span className="font-bold text-neutral-300 group-hover:text-neutral-100">
                  {p.title}
                </span>
                <span className="text-[9px] text-neutral-600 font-mono">
                  [{p.source}]
                </span>
              </div>
              <p className="text-[11px] text-neutral-500 line-clamp-2 font-sans leading-relaxed">
                "{p.text}"
              </p>
            </button>
          ))}
        </div>
      </div>

      {/* Role Agents */}
      <div className="flex-1">
        <div className="text-[10px] uppercase text-neutral-500 tracking-wider mb-2">
          // Role Agents ({workspace.roles.length})
        </div>

        <div className="flex flex-col gap-3">
          {workspace.roles.map((agent) => (
            <div key={agent.id} className="text-[11px]">
              <div className="flex items-center justify-between font-bold text-neutral-200">
                <span>{agent.name}</span>
                <span className="text-[10px] text-neutral-500 font-normal">{agent.role}</span>
              </div>
              <div className="text-[10px] text-neutral-500 mt-1 font-mono">
                {agent.expertise.slice(0, 3).join(" • ")}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Pre-ACL Security Note */}
      <div className="pt-3 border-t border-neutral-900 text-[10px] text-neutral-500">
        Pre-retrieval security boundary enforced per Bearer token scope.
      </div>
    </aside>
  );
};
