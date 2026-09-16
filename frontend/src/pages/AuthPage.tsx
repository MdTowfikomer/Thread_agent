import React, { useState } from 'react';
import { ArrowLeft, ArrowRight, Check, KeyRound } from 'lucide-react';
import { startDemoSession } from '../api';
import { ThreadLight } from '../components/ThreadLight';

interface AuthPageProps {
  onBack: () => void;
  onAuthenticated: () => void;
}

export const AuthPage: React.FC<AuthPageProps> = ({ onBack, onAuthenticated }) => {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleContinue = async () => {
    setIsSubmitting(true);
    setError(null);
    const authenticated = await startDemoSession();
    setIsSubmitting(false);
    if (authenticated) {
      onAuthenticated();
      return;
    }
    setError('Thread could not establish a session. Check that the backend is running and try again.');
  };

  return (
    <main className="relative flex min-h-screen overflow-hidden bg-[#0a0a0a] px-5 py-5 text-neutral-200 sm:p-8">
      <ThreadLight className="pointer-events-none absolute inset-0 h-full w-full opacity-55" />
      <div className="relative mx-auto flex w-full max-w-7xl flex-col">
        <header className="flex items-center justify-between">
          <button onClick={onBack} className="inline-flex items-center gap-2 text-sm text-neutral-400 transition-colors hover:text-neutral-100">
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Back to Thread
          </button>
          <span className="text-base font-semibold text-neutral-100">THREAD</span>
        </header>

        <section className="my-auto grid flex-1 items-center gap-12 py-16 lg:grid-cols-[minmax(0,1fr)_25rem] lg:gap-24">
          <div className="max-w-2xl">
            <p className="text-sm text-neutral-400">ThreadAgent live demo</p>
            <h1 className="mt-5 text-4xl font-medium leading-tight text-neutral-100 sm:text-6xl">See the context where the work happens.</h1>
            <p className="mt-6 max-w-xl text-lg leading-8 text-neutral-400">
              Explore the live Discord, Slack, Telegram, and GitHub integrations already connected to ThreadAgent.
            </p>
            <ul className="mt-10 space-y-4 text-sm text-neutral-400">
              <li className="flex items-center gap-3"><Check className="h-4 w-4 text-neutral-200" aria-hidden="true" /> Ask questions across public community context</li>
              <li className="flex items-center gap-3"><Check className="h-4 w-4 text-neutral-200" aria-hidden="true" /> Inspect source evidence and connected platforms</li>
            </ul>
          </div>

          <div className="border-y border-neutral-800 py-8 lg:border-x lg:px-8">
            <KeyRound className="h-5 w-5 text-neutral-300" aria-hidden="true" />
            <h2 className="mt-6 text-2xl font-medium text-neutral-100">Explore live demo</h2>
            <p className="mt-3 text-sm leading-6 text-neutral-500">
              No account setup is needed. This opens a one-hour, public-only viewing session for the GDG MCET demo workspace.
            </p>
            {error && <p className="mt-6 border-l border-neutral-500 pl-3 text-sm leading-6 text-neutral-300">{error}</p>}
            <button
              type="button"
              onClick={handleContinue}
              disabled={isSubmitting}
              className="mt-8 inline-flex w-full items-center justify-between bg-neutral-100 px-4 py-3 text-sm font-medium text-neutral-950 transition-colors hover:bg-white disabled:cursor-wait disabled:opacity-60"
            >
              {isSubmitting ? 'Opening demo' : 'Open demo workspace'}
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </section>

        <footer className="flex flex-wrap justify-between gap-3 border-t border-neutral-800 pt-5 text-sm text-neutral-600">
          <span>ThreadAgent</span>
          <span>Context where the work happens.</span>
        </footer>
      </div>
    </main>
  );
};
