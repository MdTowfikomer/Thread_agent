import React from 'react';
import { Terminal, LogOut, KeyRound } from 'lucide-react';

interface NavbarProps {
  workspaceName?: string;
  isAuthenticated: boolean;
  onNavigate: (route: string) => void;
  currentRoute: string;
  onOpenAuthModal?: () => void;
  onSignOut?: () => void;
  userLabel?: string;
}

export const Navbar: React.FC<NavbarProps> = ({
  workspaceName = 'GDG MCET',
  isAuthenticated,
  onNavigate,
  currentRoute,
  onOpenAuthModal,
  onSignOut,
  userLabel
}) => {
  return (
    <header className="border-b border-neutral-800 bg-[#0a0a0a] text-neutral-200 sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-12 flex items-center justify-between font-mono text-xs">
        {/* Brand & Landing Link */}
        <div className="flex items-center gap-4">
          <button
            onClick={() => onNavigate('/')}
            className="flex items-center gap-2 font-bold tracking-wider text-neutral-100 hover:text-white cursor-pointer"
          >
            <Terminal className="w-3.5 h-3.5 text-neutral-400" />
            <span>THREAD</span>
          </button>

          {/* Navigation Links (Compact text-first, subtle bottom underline for active state) */}
          <nav className="flex items-center gap-1 pl-4 border-l border-neutral-800 text-[11px]">
            <button
              onClick={() => onNavigate('/')}
              className={`px-2.5 py-1 transition-colors cursor-pointer ${
                currentRoute === '/' ? 'text-neutral-100 font-bold border-b border-neutral-100' : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              overview
            </button>
            <button
              onClick={() => onNavigate('/app')}
              className={`px-2.5 py-1 transition-colors cursor-pointer ${
                currentRoute.startsWith('/app') ? 'text-neutral-100 font-bold border-b border-neutral-100' : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              workspace
            </button>
          </nav>
        </div>

        {/* Right Section: Status Indicator, Workspace Name, Auth */}
        <div className="flex items-center gap-4 text-[11px]">
          {/* Functional Ingestion Signal */}
          <div className="hidden sm:flex items-center gap-2 text-neutral-400">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            <span>ingestion: active</span>
            <span className="text-neutral-700">|</span>
            <span>acl: enforced</span>
          </div>

          {/* Workspace Label */}
          <div className="text-neutral-400">
            ws: <span className="text-neutral-200 font-bold">{workspaceName}</span>
          </div>

          {/* Session / Authentication controls */}
          {isAuthenticated ? (
            <div className="flex items-center gap-2">
              <span className="text-neutral-300 font-mono">[{userLabel || 'authenticated'}]</span>
              {onSignOut && (
                <button
                  onClick={onSignOut}
                  title="Sign Out Session"
                  className="p-1 text-neutral-500 hover:text-neutral-200 transition-colors cursor-pointer"
                >
                  <LogOut className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          ) : (
            <button
              onClick={onOpenAuthModal}
              className="flex items-center gap-1 text-neutral-300 hover:text-white transition-colors cursor-pointer underline decoration-neutral-700"
            >
              <KeyRound className="w-3 h-3" />
              <span>auth</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
};
