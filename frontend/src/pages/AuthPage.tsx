import React, { useRef, useState } from 'react';
import { ArrowLeft, Eye, EyeOff } from 'lucide-react';
import { startDemoSession, v2Request } from '../api';

interface AuthPageProps { onBack: () => void; onAuthenticated: () => void }

export const AuthPage: React.FC<AuthPageProps> = ({ onBack, onAuthenticated }) => {
  const [signup, setSignup] = useState(false);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [visible, setVisible] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const alert = useRef<HTMLParagraphElement>(null);

  const perform = async (work: () => Promise<void>) => {
    setPending(true); setError('');
    try { await work(); onAuthenticated(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not sign in.'); requestAnimationFrame(() => alert.current?.focus()); }
    finally { setPending(false); }
  };
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    void perform(async () => { await v2Request(signup ? '/auth/signup' : '/auth/login', { method: 'POST', body: JSON.stringify({ email, password, ...(signup ? { name } : {}) }) }); });
  };

  return <main className="min-h-screen bg-[#0a0a0a] px-5 py-8 text-neutral-200 sm:px-8">
    <button onClick={onBack} className="inline-flex min-h-11 items-center gap-2 text-sm text-neutral-400 hover:text-white"><ArrowLeft size={16} aria-hidden="true" />Back to Thread</button>
    <section className="mx-auto flex min-h-[80svh] max-w-[400px] flex-col justify-center py-10">
      <p className="text-sm font-medium text-neutral-400">Thread</p>
      <h1 className="mt-5 text-3xl tracking-tight">{signup ? 'Create your account' : 'Welcome back'}</h1>
      <p className="mt-3 text-sm leading-6 text-neutral-400">Your organization’s knowledge, connected to the work.</p>
      <form onSubmit={submit} className="mt-8 space-y-5">
        {signup && <label className="v2-label">Name<input className="v2-input" autoComplete="name" required maxLength={100} value={name} onChange={e => setName(e.target.value)} /></label>}
        <label className="v2-label">Email<input className="v2-input" type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)} /></label>
        <label className="v2-label" htmlFor="account-password">Password</label>
        <div className="relative"><input id="account-password" className="v2-input pr-12" type={visible ? 'text' : 'password'} autoComplete={signup ? 'new-password' : 'current-password'} minLength={signup ? 12 : 1} maxLength={1024} required value={password} onChange={e => setPassword(e.target.value)} /><button type="button" className="absolute right-1 top-1 grid h-10 w-10 place-items-center text-neutral-400" aria-label={visible ? 'Hide password' : 'Show password'} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}</button></div>
        {signup && <p className="text-xs text-neutral-400">Use at least 12 characters. Next, create a workspace or accept an invitation.</p>}
        {error && <p ref={alert} tabIndex={-1} role="alert" className="text-sm text-red-300">{error}</p>}
        <button disabled={pending} className="v2-primary w-full">{pending ? 'Please wait…' : signup ? 'Create account' : 'Sign in'}</button>
      </form>
      <button className="mt-6 min-h-11 text-sm text-neutral-300 underline underline-offset-4" onClick={() => { setSignup(!signup); setError(''); }}>{signup ? 'Already have an account? Sign in' : 'New to Thread? Create an account'}</button>
      {!new URLSearchParams(window.location.search).has('returnTo') && <div className="mt-8 border-t border-neutral-800 pt-6"><button disabled={pending} className="v2-secondary w-full" onClick={() => void perform(async () => { if (!await startDemoSession()) throw new Error('The public demo is unavailable. Sign in to your account instead.'); })}>Explore the MCET public demo</button><p className="mt-3 text-xs leading-5 text-neutral-500">Demo access is separate from your account and includes public demo records only.</p></div>}
    </section>
  </main>;
};
