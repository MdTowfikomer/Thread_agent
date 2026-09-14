import React from 'react';
import { Network, Shield, User, Building2, ChevronDown, Check } from 'lucide-react';
import { UserRole } from '../types';

interface NavbarProps {
  workspaceName: string;
  userRole: UserRole;
  onUserRoleChange: (role: UserRole) => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  workspaceName,
  userRole,
  onUserRoleChange
}) => {
  return (
    <header className="border-b border-slate-800/80 bg-slate-950/80 backdrop-blur-md sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand & Workspace Indicator */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 via-blue-600 to-cyan-400 flex items-center justify-center shadow-lg shadow-indigo-500/20 ring-1 ring-white/20">
            <Network className="w-5 h-5 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-extrabold text-lg tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
                THREAD
              </span>
              <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                Context Agent
              </span>
            </div>
            <p className="text-xs text-slate-400 hidden sm:block">
              Search retrieves. Memory stores. Thread reconstructs.
            </p>
          </div>
        </div>

        {/* Right side controls: Active Workspace & User Profile */}
        <div className="flex items-center gap-3">
          {/* Workspace Pill */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-800 text-xs font-semibold text-slate-200 shadow-sm">
            <Building2 className="w-3.5 h-3.5 text-indigo-400" />
            <span>Workspace:</span>
            <span className="text-white font-bold">{workspaceName}</span>
          </div>

          {/* User Profile / Access Level (Demonstrates Pre-Retrieval ACL) */}
          <div className="flex items-center p-1 bg-slate-900/90 border border-slate-800 rounded-xl">
            <button
              onClick={() => onUserRoleChange('organizer')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                userRole === 'organizer'
                  ? 'bg-indigo-600 text-white shadow-md shadow-indigo-500/20'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
              title="Full internal access: Budgets, sponsor contacts, organizer logs"
            >
              <Shield className="w-3.5 h-3.5" />
              <span>Organizer Core</span>
            </button>
            <button
              onClick={() => onUserRoleChange('community')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                userRole === 'community'
                  ? 'bg-emerald-600 text-white shadow-md shadow-emerald-500/20'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
              title="Public community access: Events, workshops, and registrations"
            >
              <User className="w-3.5 h-3.5" />
              <span>Community Member</span>
            </button>
          </div>

          {/* Engine Status */}
          <div className="hidden sm:flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-[11px] font-medium text-emerald-400">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            <span>Core Active</span>
          </div>
        </div>
      </div>
    </header>
  );
};
