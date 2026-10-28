import React, { useRef, useState } from 'react';
import { AccountInfo, createWorkspace, switchWorkspace } from '../api';

export function WorkspaceSwitcher({ account, onChanged }: { account: AccountInfo; onChanged: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const trigger = useRef<HTMLButtonElement>(null);

  const change = async (id: string) => {
    setPending(true); setError('');
    try { await switchWorkspace(id); onChanged(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not switch workspace.'); }
    finally { setPending(false); }
  };
  const create = async (event: React.FormEvent) => {
    event.preventDefault(); setPending(true); setError('');
    try {
      await createWorkspace(name, description);
      dialog.current?.close(); setName(''); setDescription(''); onChanged();
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not create workspace.'); }
    finally { setPending(false); }
  };

  return <div className="flex flex-wrap items-center gap-3">
    <label className="sr-only" htmlFor="active-workspace">Active workspace</label>
    <select id="active-workspace" className="v2-input max-w-64" value={account.active_organization_id || ''} disabled={pending} onChange={e => void change(e.target.value)}>
      {!account.active_organization_id && <option value="" disabled>Select a workspace</option>}
      {account.organizations.map(org => <option key={org.id} value={org.id}>{org.name}</option>)}
    </select>
    <button ref={trigger} type="button" className="v2-secondary" onClick={() => { setError(''); dialog.current?.showModal(); }}>+ Create workspace</button>
    {error && !dialog.current?.open && <p role="alert" className="text-sm text-red-300">{error}</p>}
    <dialog ref={dialog} className="v2-dialog" onClose={() => trigger.current?.focus()} aria-labelledby="create-workspace-title">
      <form onSubmit={create} className="space-y-5">
        <h2 id="create-workspace-title" className="text-2xl tracking-tight">Create a workspace</h2>
        <p className="text-sm text-neutral-400">Give your organization its own assistant and knowledge.</p>
        <label className="v2-label">Workspace name<input autoFocus required maxLength={100} className="v2-input" value={name} onChange={e => setName(e.target.value)} /></label>
        <label className="v2-label">Description <span className="text-neutral-500">(optional)</span><textarea maxLength={2000} className="v2-input" value={description} onChange={e => setDescription(e.target.value)} /></label>
        {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
        <div className="flex justify-end gap-3"><button type="button" className="v2-secondary" onClick={() => dialog.current?.close()}>Cancel</button><button disabled={pending} className="v2-primary">{pending ? 'Creating…' : 'Create workspace'}</button></div>
      </form>
    </dialog>
  </div>;
}
