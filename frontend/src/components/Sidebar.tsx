import React from 'react';
import { CalendarDays, GitPullRequest, MessageCircle, MessagesSquare } from 'lucide-react';
import { demoPlatformLinks } from '../demoLinks';
import { OrganizationWorkspace } from '../types';

interface SidebarProps {
  workspace: OrganizationWorkspace | null;
  onSelectPrompt: (prompt: string) => void;
  activeSourceFilter: string;
  onSelectSourceFilter: (source: string) => void;
}

const prompts = [
  { label: 'Upcoming events', text: 'What upcoming events are published for GDG MCET?', icon: CalendarDays },
  { label: 'What Thread can do', text: 'What can Thread help me with?', icon: MessageCircle },
  { label: 'Repository activity', text: 'What is the latest activity in the connected repository?', icon: GitPullRequest },
];

export const Sidebar: React.FC<SidebarProps> = ({ workspace, onSelectPrompt }) => {
  return (
    <aside className="hidden h-full w-72 shrink-0 flex-col border-r border-neutral-800 bg-[#0a0a0a] px-5 py-6 lg:flex">
      <div>
        <p className="text-sm text-neutral-500">Workspace</p>
        <h2 className="mt-2 text-lg font-medium text-neutral-100">{workspace?.name || 'GDG MCET'}</h2>
        <p className="mt-3 text-sm leading-6 text-neutral-500">Ask about the public community context already connected to Thread.</p>
      </div>

      <div className="mt-10 border-t border-neutral-800 pt-6">
        <p className="text-sm text-neutral-500">Try asking</p>
        <div className="mt-3 space-y-1">
          {prompts.map(({ label, text, icon: Icon }) => (
            <button
              key={label}
              onClick={() => onSelectPrompt(text)}
              className="flex w-full items-center gap-3 px-2 py-3 text-left text-sm text-neutral-400 transition-colors hover:bg-neutral-900 hover:text-neutral-100"
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-auto border-t border-neutral-800 pt-6">
        <p className="flex items-center gap-2 text-sm text-neutral-500">
          <MessagesSquare className="h-4 w-4" aria-hidden="true" />
          Connected sources
        </p>
        <div className="mt-3 flex flex-wrap gap-x-3 gap-y-2 text-sm">
          <a href={demoPlatformLinks.discord} target="_blank" rel="noreferrer" className="text-neutral-400 transition-colors hover:text-neutral-100">Discord</a>
          <a href={demoPlatformLinks.slack} target="_blank" rel="noreferrer" className="text-neutral-400 transition-colors hover:text-neutral-100">Slack</a>
          <a href={demoPlatformLinks.telegram} target="_blank" rel="noreferrer" className="text-neutral-400 transition-colors hover:text-neutral-100">Telegram</a>
          <span className="text-neutral-600">GitHub</span>
        </div>
      </div>
    </aside>
  );
};
