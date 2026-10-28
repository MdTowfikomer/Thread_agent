import React, { useEffect, useState } from 'react';
import { AccountInfo, ApiError, getAccount, logoutSession, validateSession } from '../api';
import { WorkspaceSwitcher } from '../components/WorkspaceSwitcher';
import { WorkspacePage } from './WorkspacePage';

export function AccountWorkspacePage({ onNavigate, currentRoute }: { onNavigate: (route: string) => void; currentRoute: string }) {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [demo, setDemo] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const refresh = async () => {
    setError('');
    try { setAccount(await getAccount()); setDemo(false); }
    catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        if (await validateSession()) setDemo(true);
        else onNavigate('/auth');
      } else setError(e instanceof Error ? e.message : 'Workspace service unavailable.');
    } finally { setLoading(false); }
  };
  useEffect(() => { void refresh(); }, []);
  if (loading) return <main className="v2-empty" role="status">Loading your workspaces…</main>;
  if (error) return <main className="v2-empty"><p role="alert">{error}</p><button className="v2-secondary" onClick={() => void refresh()}>Try again</button></main>;
  if (demo) return <WorkspacePage onNavigate={onNavigate} currentRoute={currentRoute} />;
  if (!account) return null;
  if (!account.active_organization_id) return <main className="v2-empty"><div className="max-w-xl space-y-6"><p className="text-sm text-neutral-400">Thread · {account.user.name}</p><h1 className="text-3xl tracking-tight">Give your team a shared memory.</h1><p className="text-neutral-400">Create a workspace, choose one you belong to, or open your teammate’s invitation link.</p><WorkspaceSwitcher account={account} onChanged={() => void refresh()} /><button className="v2-secondary" onClick={() => void logoutSession().then(ok => { if (ok) onNavigate('/auth'); else setError('Sign out failed. Try again.'); })}>Sign out</button></div></main>;
  return <WorkspacePage key={account.active_organization_id} account={account} onAccountChanged={() => void refresh()} onNavigate={onNavigate} currentRoute={currentRoute} />;
}
