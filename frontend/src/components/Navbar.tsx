import React from 'react';
import { ArrowLeft, LogOut } from 'lucide-react';

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
  onOpenAuthModal,
  onSignOut,
  userLabel,
}) => {
  return (
    <header className="sticky top-0 z-40 border-b border-neutral-800 bg-[#0a0a0a]/95 text-neutral-200 backdrop-blur-sm">
      <div className="mx-auto flex h-16 max-w-[1600px] items-center justify-between px-5 sm:px-8">
        <div className="flex min-w-0 items-center gap-4">
          <button onClick={() => onNavigate('/')} className="text-base font-semibold text-neutral-100 transition-colors hover:text-white">
            THREAD
          </button>
          <span className="hidden h-4 w-px bg-neutral-800 sm:block" />
          <span className="truncate text-sm text-neutral-500">{workspaceName}</span>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <span className="hidden text-neutral-500 sm:block">Live community workspace</span>
          {isAuthenticated ? (
            <div className="flex items-center gap-3">
              <span className="text-neutral-400">{userLabel === 'authenticated' ? 'Demo Viewer' : userLabel}</span>
              {onSignOut && (
                <button onClick={onSignOut} title="End demo session" className="text-neutral-500 transition-colors hover:text-neutral-100">
                  <LogOut className="h-4 w-4" aria-hidden="true" />
                </button>
              )}
            </div>
          ) : (
            <button onClick={onOpenAuthModal} className="inline-flex items-center gap-2 border-b border-neutral-600 pb-1 text-neutral-100 transition-colors hover:border-neutral-100">
              Explore demo
              <ArrowLeft className="h-3.5 w-3.5 rotate-180" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>
    </header>
  );
};
