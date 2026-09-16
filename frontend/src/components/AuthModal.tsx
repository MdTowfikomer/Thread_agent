import React, { useState } from 'react';
import { ShieldAlert, X, RefreshCw, KeyRound } from 'lucide-react';
import { loginSession } from '../api';

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

  if (!isOpen) return null;

  const handleLogin = async () => {
    setAuthenticating(true);
    try {
      await loginSession("demo_organizer");
      onAuthenticated();
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
                Session Authentication
              </h3>
              <p className="text-[10px] text-neutral-500 font-sans">
                Secure HttpOnly Cookie Boundary (/api/session)
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-neutral-400 hover:text-neutral-100 hover:bg-neutral-900 cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-3.5 rounded bg-neutral-900/90 border border-neutral-800 text-neutral-300 text-xs flex items-start gap-2.5">
          <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <span className="font-bold text-neutral-100 block">// Signed-Out State</span>
            <p className="text-[11px] text-neutral-400 leading-relaxed font-sans">
              {errorDetail || 'Session is unauthenticated or invalid (401). Pasting JWT tokens into browser storage is strictly disabled.'}
            </p>
          </div>
        </div>

        <p className="text-[11px] text-neutral-500 font-sans leading-relaxed">
          Identity validation is enforced via <code className="text-neutral-300 bg-neutral-900 px-1 py-0.5 rounded font-mono">/api/session</code>. Authenticating issues an encrypted HttpOnly session cookie from the backend.
        </p>

        <div className="flex items-center justify-end gap-2 pt-3 border-t border-neutral-800">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded border border-neutral-800 hover:bg-neutral-900 text-neutral-400 hover:text-neutral-200 text-xs font-mono cursor-pointer"
          >
            Close
          </button>
          <button
            type="button"
            disabled={authenticating}
            onClick={handleLogin}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded bg-neutral-100 hover:bg-white text-neutral-900 text-xs font-bold font-mono disabled:opacity-50 cursor-pointer transition-colors"
          >
            <KeyRound className="w-3.5 h-3.5" />
            <span>{authenticating ? 'Establishing Cookie...' : 'Establish Session Cookie'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};
