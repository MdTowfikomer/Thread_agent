import React, { useState } from 'react';
import { ShieldAlert, X, KeyRound, Loader2 } from 'lucide-react';
import { startDemoSession } from '../api';

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
  const [authenticating, setAuthenticating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleLogin = async () => {
    if (authenticating) return;
    setAuthenticating(true);
    setError(null);
    try {
      const success = await startDemoSession();
      if (success) {
        onAuthenticated();
        return;
      }
      setError('Thread could not establish a session. Check that the backend is running and try again.');
    } catch {
      setError('Connection failed. Please try again.');
    } finally {
      setAuthenticating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-xs animate-in fade-in duration-150 font-mono text-xs">
      <div className="bg-[#0a0a0a] border border-neutral-800 rounded-lg p-6 max-w-md w-full shadow-2xl space-y-5 text-neutral-200">
        <div className="flex items-center justify-between pb-3 border-b border-neutral-800">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-neutral-900 border border-neutral-700 text-neutral-200 flex items-center justify-center font-bold text-xs">
              //
            </div>
            <div>
              <h3 className="font-bold text-xs uppercase tracking-wider text-neutral-100">
                Live Demo Access
              </h3>
              <p className="text-[10px] text-neutral-500 font-sans">
                Public-only workspace session
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={authenticating}
            className="p-1 rounded text-neutral-400 hover:text-neutral-100 hover:bg-neutral-900 cursor-pointer disabled:opacity-40"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-3.5 rounded bg-neutral-900/90 border border-neutral-800 text-neutral-300 text-xs flex items-start gap-2.5">
          <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <span className="font-bold text-neutral-100 block">Demo access required</span>
            <p className="text-[11px] text-neutral-400 leading-relaxed font-sans">
              {error || errorDetail || 'Open a public-only demo session to continue.'}
            </p>
          </div>
        </div>

        <p className="text-[11px] text-neutral-500 font-sans leading-relaxed">
          Thread issues a short-lived HttpOnly session cookie for the fixed Demo Viewer identity. The browser cannot choose its role or organization.
        </p>

        <div className="flex items-center justify-end gap-2 pt-3 border-t border-neutral-800">
          <button
            type="button"
            onClick={onClose}
            disabled={authenticating}
            className="px-3 py-1.5 rounded border border-neutral-800 hover:bg-neutral-900 text-neutral-400 hover:text-neutral-200 text-xs font-mono cursor-pointer disabled:opacity-40"
          >
            Close
          </button>
          <button
            type="button"
            disabled={authenticating}
            onClick={handleLogin}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded bg-neutral-100 hover:bg-white text-neutral-900 text-xs font-bold font-mono disabled:opacity-50 cursor-pointer transition-colors"
          >
            {authenticating ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin text-neutral-900" />
            ) : (
              <KeyRound className="w-3.5 h-3.5" />
            )}
            <span>{authenticating ? 'Opening demo...' : 'Open demo workspace'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};
