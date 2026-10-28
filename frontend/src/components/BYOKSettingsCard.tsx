import React, { useEffect, useRef, useState } from 'react';
import { v2Request } from '../api';

interface CredentialInfo {
  provider: 'google';
  masked_key: string | null;
  status: 'unconfigured' | 'active' | 'invalid' | 'revoked';
  model_name: string;
  embedding_model: string;
  embedding_dimensions: number;
  supported_models: string[];
  last_validated_at: string | null;
}

export function BYOKSettingsCard({ orgId }: { orgId: string }) {
  const [credential, setCredential] = useState<CredentialInfo | null>(null);
  const [model, setModel] = useState('');
  const [key, setKey] = useState('');
  const [rotating, setRotating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  const removeButton = useRef<HTMLButtonElement>(null);
  const apiKeyInput = useRef<HTMLInputElement>(null);
  const path = `/organizations/${encodeURIComponent(orgId)}/credentials/model`;

  const load = async () => {
    setLoading(true); setError('');
    try { const data = await v2Request<CredentialInfo>(path); setCredential(data); setModel(data.model_name); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not load the model connection.'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); return () => { setKey(''); }; }, [orgId]);
  const save = async (event: React.FormEvent) => {
    event.preventDefault(); setPending(true); setError(''); setNotice('');
    try {
      const data = await v2Request<CredentialInfo>(path, { method: 'POST', body: JSON.stringify({ provider: 'google', api_key: key, model_name: model }) });
      setCredential(data); setModel(data.model_name); setRotating(false); setNotice('Provider access validated. Your organization’s key is saved.');
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not validate this key.'); }
    finally { setKey(''); setPending(false); }
  };
  const remove = async () => {
    setPending(true); setError(''); setNotice('');
    try {
      setCredential(await v2Request<CredentialInfo>(path, { method: 'DELETE' }));
      setKey(''); setRotating(false); dialog.current?.close(); setNotice('Saved key removed. Reconnect a model to run new queries.');
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not remove the saved key.'); }
    finally { setPending(false); }
  };
  const showForm = credential?.status !== 'active' || rotating;

  return <section className="space-y-5 border-t border-neutral-800 pt-6" aria-labelledby="model-connection-heading">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 id="model-connection-heading" className="text-xl">Your model connection</h2><p className="mt-2 text-sm leading-6 text-neutral-400">Bring your organization’s Google Gemini API key. Model usage is billed to your Google project.</p></div>
      {credential && <span className="py-1 text-sm capitalize text-neutral-300">{credential.status === 'unconfigured' ? 'Not connected' : credential.status}</span>}
    </div>
    {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
    {notice && <p role="status" className="text-sm text-neutral-300">{notice}</p>}
    {loading ? <p role="status" className="text-sm text-neutral-400">Loading model settings…</p> : !credential ? <button type="button" className="v2-secondary" onClick={() => void load()}>Retry connection settings</button> : <>
      {credential.masked_key && <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[9rem_1fr]"><dt className="text-neutral-400">Saved key</dt><dd className="font-mono">{credential.masked_key}</dd><dt className="text-neutral-400">Chat model</dt><dd>{credential.model_name}</dd>{credential.last_validated_at && <><dt className="text-neutral-400">Last validated</dt><dd>{new Date(credential.last_validated_at).toLocaleString()}</dd></>}</dl>}
      {showForm ? <form onSubmit={event => void save(event)} className="space-y-5">
        <fieldset disabled={pending} className="space-y-5">
          <label className="v2-label">Provider<select className="v2-input" value="google" disabled><option value="google">Google Gemini</option></select></label>
          <label className="v2-label">Chat model<select required className="v2-input" value={model} onChange={e => setModel(e.target.value)}>{credential.supported_models.map(id => <option key={id} value={id}>{id}</option>)}</select></label>
          <label className="v2-label">{rotating ? 'Replacement API key' : 'API key'}<input ref={apiKeyInput} className="v2-input font-mono" type="password" autoComplete="new-password" spellCheck={false} required minLength={12} maxLength={1024} value={key} onChange={e => setKey(e.target.value)} aria-describedby="model-key-help" /></label>
          <p id="model-key-help" className="text-xs leading-5 text-neutral-400">Test &amp; save checks access to the chat and embedding models. Future requests still depend on your project’s quota.</p>
          <div className="flex flex-wrap gap-3"><button className="v2-primary">{pending ? 'Validating…' : 'Test & save'}</button>{rotating && <button type="button" className="v2-secondary" onClick={() => { setRotating(false); setKey(''); setError(''); }}>Cancel</button>}</div>
        </fieldset>
      </form> : <button type="button" className="v2-secondary" onClick={() => { setRotating(true); setNotice(''); requestAnimationFrame(() => apiKeyInput.current?.focus()); }}>Rotate key or change chat model</button>}
      <p className="text-sm leading-6 text-neutral-400">Embedding model: <span className="text-neutral-300">{credential.embedding_model.replace('models/', '')} · {credential.embedding_dimensions} dimensions</span>. Changing the chat model keeps this configuration unchanged.</p>
      {(credential.status === 'active' || credential.status === 'invalid') && <button ref={removeButton} type="button" disabled={pending} className="v2-secondary" onClick={() => { setError(''); dialog.current?.showModal(); }}>Remove saved key</button>}
    </>}
    <dialog ref={dialog} className="v2-dialog" aria-labelledby="remove-key-title" onClose={() => (removeButton.current || apiKeyInput.current)?.focus()}><h2 id="remove-key-title" className="text-xl">Remove the saved API key?</h2><p className="mt-3 text-sm leading-6 text-neutral-400">New queries and embedding jobs will need a new connection. This removes the key from Thread; it does not revoke it at Google.</p>{error && <p role="alert" className="mt-3 text-sm text-red-300">{error}</p>}<div className="mt-6 flex justify-end gap-3"><button type="button" className="v2-secondary" onClick={() => dialog.current?.close()}>Cancel</button><button type="button" disabled={pending} className="v2-primary" onClick={() => void remove()}>{pending ? 'Removing…' : 'Remove key'}</button></div></dialog>
  </section>;
}
