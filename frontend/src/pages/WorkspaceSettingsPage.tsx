import React, { useEffect, useRef, useState } from 'react';
import { AccountInfo, AppRole, v2Request, WorkspaceDetails, WorkspaceMember } from '../api';
import { RoleAgent } from '../types';
import { BYOKSettingsCard } from '../components/BYOKSettingsCard';

export function WorkspaceSettingsPage({ orgId, account, onChanged }: { orgId: string; account: AccountInfo; onChanged: () => void }) {
  const [workspace, setWorkspace] = useState<WorkspaceDetails | null>(null);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [email, setEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<'member' | 'admin'>('member');
  const [invitation, setInvitation] = useState('');
  const [rolesText, setRolesText] = useState('[]');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [pending, setPending] = useState(false);
  const [confirmation, setConfirmation] = useState<{ member: WorkspaceMember; role?: AppRole } | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const base = `/organizations/${encodeURIComponent(orgId)}`;
  const myRole = account.organizations.find(org => org.id === orgId)?.role;
  const canManage = myRole === 'owner' || myRole === 'admin';

  const load = async () => {
    const [details, people] = await Promise.all([v2Request<WorkspaceDetails>(base), v2Request<WorkspaceMember[]>(`${base}/members`)]);
    setWorkspace(details); setMembers(people); setRolesText(JSON.stringify(details.configured_roles, null, 2));
  };
  useEffect(() => { let active = true; load().catch(e => { if (active) setError(e.message); }); return () => { active = false; }; }, [orgId]);
  const action = async (work: () => Promise<void>) => {
    setPending(true); setError(''); setNotice('');
    try { await work(); } catch (e) { setError(e instanceof Error ? e.message : 'Request failed.'); }
    finally { setPending(false); }
  };
  const save = (event: React.FormEvent) => {
    event.preventDefault();
    void action(async () => {
      if (!workspace) return;
      let roles: RoleAgent[];
      try { roles = JSON.parse(rolesText); if (!Array.isArray(roles)) throw new Error(); }
      catch { throw new Error('Specialists must be a JSON array.'); }
      await v2Request(base, { method: 'PATCH', body: JSON.stringify({ name: workspace.name, description: workspace.description, default_agent_name: workspace.default_agent_name, system_prompt: workspace.system_prompt, configured_roles: roles }) });
      setNotice('Workspace settings saved.'); onChanged();
    });
  };
  const invite = (event: React.FormEvent) => {
    event.preventDefault();
    void action(async () => {
      const result = await v2Request<{ invitation_path: string }>(`${base}/invitations`, { method: 'POST', body: JSON.stringify({ email, role: inviteRole }) });
      setInvitation(`${window.location.origin}${result.invitation_path}`); setNotice('Invitation created. Share this link with your teammate. It expires in seven days.');
    });
  };
  const askConfirmation = (member: WorkspaceMember, role?: AppRole) => {
    previousFocus.current = document.activeElement as HTMLElement;
    setConfirmation({ member, role }); dialog.current?.showModal();
  };
  const confirm = () => void action(async () => {
    if (!confirmation) return;
    const { member, role } = confirmation;
    await v2Request(`${base}/members/${encodeURIComponent(member.id)}`, { method: role ? 'PATCH' : 'DELETE', ...(role ? { body: JSON.stringify({ role }) } : {}) });
    dialog.current?.close(); setConfirmation(null); await load(); onChanged(); setNotice(role ? 'Member role updated.' : 'Member removed.');
  });

  return <section className="mx-auto max-w-4xl space-y-10 px-5 py-10 sm:px-8">
    <div><h1 className="text-3xl tracking-tight">Workspace settings</h1><p className="mt-3 text-neutral-400">Manage your assistant and the people who can use it.</p></div>
    {error && <p role="alert" className="text-red-300">{error}</p>}
    {notice && <p role="status" className="text-neutral-300">{notice}</p>}
    {!workspace ? <p className="text-neutral-400">{error ? 'Settings could not be loaded.' : 'Loading settings…'}</p> : <>
      {canManage ? <BYOKSettingsCard key={orgId} orgId={orgId} /> : <section className="border-t border-neutral-800 pt-6"><h2 className="text-xl">Model connection</h2><p className="mt-2 text-sm text-neutral-400">An owner or administrator manages this organization’s model connection.</p></section>}
      <form onSubmit={save} className="space-y-5 border-t border-neutral-800 pt-6">
        <h2 className="text-xl">Organization and assistant</h2>
        <fieldset disabled={!canManage || pending} className="space-y-5 disabled:opacity-70">
          <label className="v2-label">Workspace name<input required maxLength={100} className="v2-input" value={workspace.name} onChange={e => setWorkspace({ ...workspace, name: e.target.value })} /></label>
          <label className="v2-label">Description<textarea maxLength={2000} className="v2-input" value={workspace.description} onChange={e => setWorkspace({ ...workspace, description: e.target.value })} /></label>
          <label className="v2-label">Assistant name<input required maxLength={100} className="v2-input" value={workspace.default_agent_name} onChange={e => setWorkspace({ ...workspace, default_agent_name: e.target.value })} /></label>
          <label className="v2-label">Assistant instructions<textarea maxLength={8000} rows={3} className="v2-input" value={workspace.system_prompt} onChange={e => setWorkspace({ ...workspace, system_prompt: e.target.value })} /></label>
          <details className="text-sm text-neutral-400"><summary className="cursor-pointer py-2">Optional specialist configuration</summary>
            <p className="my-3 leading-6">Leave an empty array for the general assistant. Each specialist needs id, name, role, department, style, avatar, and an expertise array.</p>
            <label className="v2-label">Specialists (JSON)<textarea rows={7} className="v2-input font-mono" value={rolesText} onChange={e => setRolesText(e.target.value)} /></label>
          </details>
          {canManage && <button className="v2-primary">{pending ? 'Saving…' : 'Save settings'}</button>}
        </fieldset>
        {!canManage && <p className="text-sm text-neutral-400">An owner or administrator can change these settings.</p>}
      </form>
      <section className="space-y-5 border-t border-neutral-800 pt-6"><h2 className="text-xl">Members</h2>
        <ul className="divide-y divide-neutral-800">{members.map(member => <li key={member.id} className="flex flex-wrap items-center justify-between gap-3 py-4">
          <div><p>{member.name}{member.id === account.user.id ? ' (you)' : ''}</p><p className="text-sm text-neutral-400">{member.email}</p></div>
          <div className="flex items-center gap-3"><span className="text-sm text-neutral-400">{member.role}</span>
            {canManage && member.role !== 'owner' && (myRole === 'owner' || member.role === 'member') && <>
              {myRole === 'owner' && <><button disabled={pending} className="v2-secondary" onClick={() => askConfirmation(member, member.role === 'admin' ? 'member' : 'admin')}>{member.role === 'admin' ? 'Make member' : 'Make admin'}</button><button disabled={pending} className="v2-secondary" onClick={() => askConfirmation(member, 'owner')}>Transfer ownership</button></>}
              <button disabled={pending} className="v2-secondary" onClick={() => askConfirmation(member)}>Remove</button>
            </>}
          </div>
        </li>)}</ul>
      </section>
      {canManage && <form onSubmit={invite} className="space-y-5 border-t border-neutral-800 pt-6"><h2 className="text-xl">Invite a teammate</h2>
        <label className="v2-label">Email<input type="email" required className="v2-input" value={email} onChange={e => { setEmail(e.target.value); setInvitation(''); }} /></label>
        <label className="v2-label">Role<select className="v2-input" value={inviteRole} onChange={e => setInviteRole(e.target.value as 'member' | 'admin')}><option value="member">Member</option>{myRole === 'owner' && <option value="admin">Administrator</option>}</select></label>
        <button disabled={pending} className="v2-primary">Create invitation link</button>
        {invitation && <label className="v2-label">Share this private invitation link<input className="v2-input" readOnly value={invitation} onFocus={e => e.target.select()} /></label>}
      </form>}
    </>}
    <dialog ref={dialog} className="v2-dialog" onClose={() => previousFocus.current?.focus()} aria-labelledby="membership-confirm-title"><h2 id="membership-confirm-title" className="text-xl">{confirmation?.role === 'owner' ? 'Transfer workspace ownership?' : confirmation?.role ? 'Change member role?' : 'Remove this member?'}</h2><p className="mt-3 text-neutral-400">{confirmation?.role === 'owner' ? `You will become an administrator. ${confirmation.member.name} will be the owner.` : `This change applies to ${confirmation?.member.name} on their next request.`}</p>{error && <p role="alert" className="mt-3 text-sm text-red-300">{error}</p>}<div className="mt-6 flex justify-end gap-3"><button className="v2-secondary" onClick={() => dialog.current?.close()}>Cancel</button><button disabled={pending} className="v2-primary" onClick={confirm}>Confirm change</button></div></dialog>
  </section>;
}
