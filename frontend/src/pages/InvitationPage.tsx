import React, { useState } from 'react';
import { ApiError, v2Request } from '../api';

export function InvitationPage({ token, onNavigate }: { token: string; onNavigate: (route: string) => void }) {
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [needsAuth, setNeedsAuth] = useState(false);
  const accept = async () => {
    setPending(true); setError('');
    try { await v2Request(`/invitations/${encodeURIComponent(token)}/accept`, { method: 'POST' }); onNavigate('/app'); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not accept invitation.'); setNeedsAuth(e instanceof ApiError && e.status === 401); }
    finally { setPending(false); }
  };
  return <main className="v2-empty"><section className="max-w-lg space-y-6"><p className="text-sm text-neutral-400">Thread</p><h1 className="text-3xl tracking-tight">Join your team’s workspace</h1><p className="text-neutral-400">Sign in with the email address your teammate invited, then accept to join.</p>{error && <p role="alert" className="text-red-300">{error}</p>}{needsAuth ? <button className="v2-primary" onClick={() => onNavigate(`/auth?returnTo=${encodeURIComponent(`/invite/${token}`)}`)}>Sign in or create an account</button> : <button disabled={pending} className="v2-primary" onClick={() => void accept()}>{pending ? 'Joining…' : 'Accept invitation'}</button>}</section></main>;
}
