import React from 'react';
import { OrganizationWorkspace, UserRole } from '../types';
import { Users, Sparkles, ShieldCheck, Lock, ExternalLink } from 'lucide-react';

interface SidebarProps {
  workspace: OrganizationWorkspace | null;
  onSelectPrompt: (prompt: string) => void;
  userRole: UserRole;
}

export const Sidebar: React.FC<SidebarProps> = ({
  workspace,
  onSelectPrompt,
  userRole
}) => {
  if (!workspace) return null;

  const samplePrompts = [
    {
      title: "DevFest Venue Approval",
      text: "Where is DevFest taking place and has it been approved?",
      role: "Lead Organizer"
    },
    {
      title: "GenAI Workshop Setup",
      text: "What are the prerequisites for the GenAI workshop and where is the repo?",
      role: "Tech Lead"
    },
    {
      title: "Swag & Catering Budget",
      text: "What is our internal budget for attendee t-shirts and swag?",
      role: "Sponsorship & Finance Lead",
      badge: "Internal Core"
    },
    {
      title: "RSVP & Participation Rules",
      text: "How do community members register and what are certificate criteria?",
      role: "Community Lead"
    }
  ];

  return (
    <aside className="w-80 border-r border-slate-800/80 bg-slate-950/60 p-4 flex flex-col gap-6 overflow-y-auto hidden lg:flex">
      {/* Workspace Header */}
      <div>
        <div className="flex items-center gap-2 mb-1.5">
          <span className="w-2 h-2 rounded-full bg-indigo-500"></span>
          <h2 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
            Active Workspace
          </h2>
        </div>
        <h3 className="text-base font-extrabold text-white tracking-tight">
          {workspace.name}
        </h3>
        <p className="text-xs text-slate-400 mt-1 leading-relaxed">
          {workspace.description}
        </p>
      </div>

      {/* Suggested Queries */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <Sparkles className="w-4 h-4 text-amber-400" />
          <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wider">
            Reconstruct Context
          </h4>
        </div>
        <div className="flex flex-col gap-2">
          {samplePrompts.map((p, idx) => (
            <button
              key={idx}
              onClick={() => onSelectPrompt(p.text)}
              className="text-left p-2.5 rounded-xl bg-slate-900/80 border border-slate-800/90 hover:border-indigo-500/50 hover:bg-indigo-950/20 transition-all group cursor-pointer"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-semibold text-slate-200 group-hover:text-indigo-300">
                  {p.title}
                </span>
                {p.badge && (
                  <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                    {p.badge}
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-400 line-clamp-2">
                "{p.text}"
              </p>
            </button>
          ))}
        </div>
      </div>

      {/* Role Agents */}
      <div className="flex-1">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Users className="w-4 h-4 text-indigo-400" />
            <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wider">
              Role Agents ({workspace.roles.length})
            </h4>
          </div>
        </div>

        <div className="flex flex-col gap-2.5">
          {workspace.roles.map((agent) => (
            <div
              key={agent.id}
              className="p-2.5 rounded-xl bg-slate-900/60 border border-slate-800/80 hover:border-slate-700 transition-all"
            >
              <div className="flex items-center gap-2.5 mb-1.5">
                <img
                  src={agent.avatar}
                  alt={agent.name}
                  className="w-8 h-8 rounded-lg bg-slate-800 ring-1 ring-slate-700"
                />
                <div className="min-w-0 flex-1">
                  <h5 className="text-xs font-bold text-slate-200 truncate">
                    {agent.name}
                  </h5>
                  <p className="text-[11px] text-indigo-400 font-medium truncate">
                    {agent.role}
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap gap-1 mt-2">
                {agent.expertise.slice(0, 3).map((tag, tIdx) => (
                  <span
                    key={tIdx}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700/60"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Security Architecture Principle Box */}
      <div className="p-3 rounded-xl bg-slate-900/50 border border-slate-800/80 text-[11px] text-slate-400">
        <div className="flex items-center gap-1.5 text-slate-300 font-semibold mb-1">
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
          <span>Pre-Retrieval ACL Active</span>
        </div>
        <p className="text-[10px] leading-relaxed text-slate-400">
          Thread enforces permissions <strong>before retrieval</strong>, not after the LLM generates an answer. 
          {userRole === 'community'
            ? ' As a Community Member, confidential budget numbers and private roldexes are omitted from the vector search space entirely.'
            : ' As an Organizer Core member, you have authenticated access to internal documents and financial allocations.'}
        </p>
      </div>
    </aside>
  );
};
