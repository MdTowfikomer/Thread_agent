import React, { useState } from 'react';
import { KeyRound, ShieldAlert, X, Check } from 'lucide-react';
import { setAuthToken } from '../api';

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onAuthenticated: () => void;
  errorDetail?: string;
}

export const AuthModal: React.FC<AuthModalProps> = ({
  isOpen,
  onClose,
  onAuthenticated,
  errorDetail,
}) => {
  const [tokenInput, setTokenInput] = useState('');
  const [remember, setRemember] = useState(true);

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!tokenInput.trim()) return;
    setAuthToken(tokenInput.trim(), remember);
    onAuthenticated();
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-xs animate-in fade-in duration-150">
      <div className="bg-white border border-slate-200 rounded-2xl p-6 max-w-md w-full shadow-2xl space-y-5 text-slate-900">
        <div className="flex items-center justify-between pb-3 border-b border-slate-100">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center font-bold">
              <KeyRound className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-extrabold text-sm text-slate-900">
                Authenticate Session
              </h3>
              <p className="text-[11px] text-slate-500">
                Bearer Token Security Boundary
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {errorDetail && (
          <div className="p-3 rounded-xl bg-amber-50 border border-amber-200 text-amber-900 text-xs flex items-start gap-2">
            <ShieldAlert className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
            <div>
              <span className="font-bold block">Authentication Required (401)</span>
              <p className="text-[11px] text-amber-800 leading-snug mt-0.5">
                {errorDetail}
              </p>
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-bold text-slate-700 mb-1">
              Bearer Access Token (JWT)
            </label>
            <input
              type="text"
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              placeholder="Paste Bearer token (e.g. eyJhbGci...)"
              className="w-full bg-slate-50 border border-slate-200 focus:border-emerald-600 focus:ring-1 focus:ring-emerald-600/30 rounded-xl px-3 py-2 text-xs font-mono text-slate-900 placeholder:text-slate-400 outline-none"
            />
            <p className="text-[10px] text-slate-400 mt-1">
              User identity, organization ID, and allowed permission scopes are derived strictly from this bearer token.
            </p>
          </div>

          <div className="flex items-center gap-2 text-xs text-slate-600">
            <input
              type="checkbox"
              id="remember"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              className="rounded border-slate-300 text-emerald-600 focus:ring-emerald-500 cursor-pointer"
            />
            <label htmlFor="remember" className="cursor-pointer font-medium">
              Persist session token in localStorage
            </label>
          </div>

          <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
            <button
              type="button"
              onClick={onClose}
              className="px-3.5 py-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100 cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!tokenInput.trim()}
              className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold shadow-xs disabled:opacity-40 transition-colors cursor-pointer"
            >
              Save & Authenticate
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
