import React, { useState } from 'react';
import {
  ArrowDown,
  ArrowRight,
  Check,
  LockKeyhole,
  MessageCircle,
  Search,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { AsciiArt } from '@/components/ui/minimal-2';
import { ThreadLight } from '../components/ThreadLight';

interface LandingPageProps {
  onOpenWorkspace: () => void;
}

type Channel = 'Discord' | 'Slack' | 'Telegram' | 'GitHub';

const channels: Array<{ name: Channel; description: string }> = [
  { name: 'Discord', description: 'Answer in the channel where the question begins.' },
  { name: 'Slack', description: 'Keep team conversations connected to their shared history.' },
  { name: 'Telegram', description: 'Bring community discussions into the same memory layer.' },
  { name: 'GitHub', description: 'Connect project activity, pull requests, and decisions.' },
];

const capabilityRows = [
  ['Events and workshops', 'Dates, speakers, locations, and RSVP links from approved records.'],
  ['Conversation summaries', 'Clear takeaways from the channel where the discussion happened.'],
  ['Repository help', 'Recent project activity, open work, and contribution context.'],
  ['Resources and FAQs', 'Approved guides, community links, and useful answers when they are needed.'],
];

export const LandingPage: React.FC<LandingPageProps> = ({ onOpenWorkspace }) => {
  const [selectedChannel, setSelectedChannel] = useState<Channel>('Discord');
  const selected = channels.find((channel) => channel.name === selectedChannel) ?? channels[0];

  return (
    <div className="min-h-screen overflow-x-hidden bg-[#0a0a0a] text-neutral-200">
      <header className="sticky top-0 z-30 border-b border-neutral-800/80 bg-[#0a0a0a]/95 px-5 backdrop-blur-sm sm:px-8">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between">
          <a href="#top" className="text-base font-semibold text-neutral-100" aria-label="Thread home">
            THREAD
          </a>
          <nav className="hidden items-center gap-7 text-sm text-neutral-500 md:flex" aria-label="Landing page sections">
            <a className="transition-colors hover:text-neutral-100" href="#context">Context</a>
            <a className="transition-colors hover:text-neutral-100" href="#channels">Channels</a>
            <a className="transition-colors hover:text-neutral-100" href="#boundaries">Boundaries</a>
          </nav>
          <button
            onClick={onOpenWorkspace}
            className="inline-flex items-center gap-2 border-b border-neutral-600 pb-1 text-sm text-neutral-100 transition-colors hover:border-neutral-100"
          >
            Open workspace
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </header>

      <main id="top">
        <section className="relative flex min-h-[calc(72svh-4rem)] items-end overflow-hidden border-b border-neutral-800 px-5 pb-12 pt-20 sm:px-8 sm:pb-16 lg:px-12">
          <div className="pointer-events-none absolute inset-0 opacity-35">
            <AsciiArt className="h-full w-full object-cover" />
          </div>
          <div className="relative mx-auto flex w-full max-w-7xl flex-col justify-end">
            <p className="mb-5 text-sm text-neutral-400">A community agent with a long memory.</p>
            <h1 className="max-w-4xl text-5xl font-semibold leading-[1.04] text-neutral-100 sm:text-6xl lg:text-8xl">
              The AI Agent joins the work.
            </h1>
            <div className="mt-8 grid max-w-3xl gap-7 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
              <p className="max-w-xl text-lg leading-8 text-neutral-300">
                ThreadAgent lives inside the spaces where your community already plans, discusses, and builds. Ask there. Keep the context there.
              </p>
              <button
                onClick={onOpenWorkspace}
                className="inline-flex w-fit items-center gap-2 text-sm text-neutral-100 transition-transform hover:translate-x-1"
              >
                Enter Thread
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
            <a href="#context" className="mt-14 inline-flex w-fit items-center gap-2 text-sm text-neutral-500 transition-colors hover:text-neutral-100">
              See how it works
              <ArrowDown className="h-4 w-4" aria-hidden="true" />
            </a>
          </div>
        </section>

        <section id="context" className="border-b border-neutral-800 px-5 py-20 sm:px-8 sm:py-28 lg:px-12">
          <div className="mx-auto grid max-w-7xl gap-10 lg:grid-cols-12 lg:gap-16">
            <p className="text-sm text-neutral-500 lg:col-span-2">01 / The problem</p>
            <div className="lg:col-span-8">
              <h2 className="max-w-4xl text-3xl font-medium leading-tight text-neutral-100 sm:text-5xl">
                AI should not make people leave the conversation to find an answer.
              </h2>
              <div className="mt-10 grid gap-6 text-lg leading-8 text-neutral-400 md:grid-cols-2">
                <p>
                  Most AI agents live in a separate tool. People leave where they are working, bring over a question, then try to reconstruct the missing context.
                </p>
                <p>
                  Meanwhile, decisions, event details, project updates, and useful resources scatter across the places a community uses every day.
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="border-b border-neutral-800 px-5 py-20 sm:px-8 sm:py-28 lg:px-12">
          <div className="mx-auto max-w-7xl">
            <div className="grid gap-10 lg:grid-cols-12 lg:gap-16">
              <p className="text-sm text-neutral-500 lg:col-span-2">02 / One memory</p>
              <div className="lg:col-span-8">
                <h2 className="max-w-3xl text-3xl font-medium leading-tight text-neutral-100 sm:text-5xl">
                  Your community already has the context. Thread makes it usable.
                </h2>
              </div>
            </div>
            <div className="mt-16 grid border-y border-neutral-800 sm:grid-cols-2 lg:grid-cols-4">
              {channels.map((channel, index) => (
                <div key={channel.name} className="min-h-44 border-neutral-800 p-5 sm:border-r sm:last:border-r-0 lg:border-r lg:last:border-r-0">
                  <span className="text-sm text-neutral-600">0{index + 1}</span>
                  <h3 className="mt-8 text-lg font-medium text-neutral-100">{channel.name}</h3>
                  <p className="mt-3 text-sm leading-6 text-neutral-500">{channel.description}</p>
                </div>
              ))}
            </div>
            <div className="mt-7 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-neutral-500">
              <span>Messages and project activity become traceable organizational memory.</span>
              <ArrowRight className="h-4 w-4 text-neutral-700" aria-hidden="true" />
              <span className="text-neutral-300">The answer stays grounded in the right context.</span>
            </div>
          </div>
        </section>

        <section id="channels" className="border-b border-neutral-800 px-5 py-20 sm:px-8 sm:py-28 lg:px-12">
          <div className="mx-auto grid max-w-7xl gap-12 lg:grid-cols-12 lg:gap-16">
            <div className="lg:col-span-4">
              <p className="text-sm text-neutral-500">03 / Where work happens</p>
              <h2 className="mt-6 text-3xl font-medium leading-tight text-neutral-100 sm:text-5xl">
                Ask once. Stay where you are.
              </h2>
              <p className="mt-6 max-w-md text-lg leading-8 text-neutral-400">
                The same assistant can meet a member in their channel, preserve its source context, and respond in the format that fits the platform.
              </p>
            </div>
            <div className="border-y border-neutral-800 lg:col-span-8 lg:border-y-0 lg:border-l">
              <div className="grid border-b border-neutral-800 sm:grid-cols-4">
                {channels.map((channel) => (
                  <button
                    key={channel.name}
                    type="button"
                    onClick={() => setSelectedChannel(channel.name)}
                    aria-pressed={selectedChannel === channel.name}
                    className={`min-h-14 border-b border-neutral-800 px-4 text-left text-sm transition-colors sm:border-b-0 sm:border-r sm:last:border-r-0 ${selectedChannel === channel.name ? 'bg-neutral-100 text-neutral-950' : 'text-neutral-500 hover:bg-neutral-900 hover:text-neutral-100'}`}
                  >
                    {channel.name}
                  </button>
                ))}
              </div>
              <div className="grid min-h-80 gap-8 px-5 py-8 sm:px-8 md:grid-cols-[minmax(0,1fr)_11rem] md:items-end">
                <div>
                  <div className="flex items-center gap-2 text-sm text-neutral-500">
                    <MessageCircle className="h-4 w-4" aria-hidden="true" />
                    {selected.name}
                  </div>
                  <p className="mt-8 max-w-xl text-2xl leading-snug text-neutral-100">
                    “What is the next workshop, and where can I register?”
                  </p>
                  <div className="mt-8 border-l border-neutral-700 pl-4 text-sm leading-6 text-neutral-400">
                    Thread checks approved event records, preserves the channel’s access boundary, and answers with the details available to this member.
                  </div>
                </div>
                <div className="border-t border-neutral-800 pt-5 text-sm text-neutral-500 md:border-t-0 md:border-l md:pl-6 md:pt-0">
                  <span className="block text-neutral-100">Same assistant</span>
                  <span className="mt-2 block">{selected.description}</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id="boundaries" className="border-b border-neutral-800 px-5 py-20 sm:px-8 sm:py-28 lg:px-12">
          <div className="mx-auto grid max-w-7xl gap-12 lg:grid-cols-12 lg:gap-16">
            <div className="lg:col-span-4">
              <p className="text-sm text-neutral-500">04 / Context with boundaries</p>
              <h2 className="mt-6 text-3xl font-medium leading-tight text-neutral-100 sm:text-5xl">
                Shared context does not mean shared access.
              </h2>
            </div>
            <dl className="divide-y divide-neutral-800 border-y border-neutral-800 lg:col-span-8">
              <div className="grid gap-5 py-6 sm:grid-cols-[2rem_minmax(0,1fr)]">
                <ShieldCheck className="h-5 w-5 text-neutral-300" aria-hidden="true" />
                <div>
                  <dt className="text-lg text-neutral-100">Permission-aware retrieval</dt>
                  <dd className="mt-2 max-w-xl text-sm leading-6 text-neutral-500">Thread checks access before search, so private working context cannot surface in a public conversation.</dd>
                </div>
              </div>
              <div className="grid gap-5 py-6 sm:grid-cols-[2rem_minmax(0,1fr)]">
                <Search className="h-5 w-5 text-neutral-300" aria-hidden="true" />
                <div>
                  <dt className="text-lg text-neutral-100">Grounded responses</dt>
                  <dd className="mt-2 max-w-xl text-sm leading-6 text-neutral-500">Organizational answers draw from approved records, while ordinary questions receive a direct conversational response.</dd>
                </div>
              </div>
              <div className="grid gap-5 py-6 sm:grid-cols-[2rem_minmax(0,1fr)]">
                <LockKeyhole className="h-5 w-5 text-neutral-300" aria-hidden="true" />
                <div>
                  <dt className="text-lg text-neutral-100">Traceable sources</dt>
                  <dd className="mt-2 max-w-xl text-sm leading-6 text-neutral-500">Every useful answer can keep a clear path back to the conversation, record, or project activity that supports it.</dd>
                </div>
              </div>
            </dl>
          </div>
        </section>

        <section className="border-b border-neutral-800 px-5 py-20 sm:px-8 sm:py-28 lg:px-12">
          <div className="mx-auto grid max-w-7xl gap-12 lg:grid-cols-12 lg:gap-16">
            <div className="lg:col-span-4">
              <p className="text-sm text-neutral-500">05 / Useful in the moment</p>
              <h2 className="mt-6 text-3xl font-medium leading-tight text-neutral-100 sm:text-5xl">
                More than a search box.
              </h2>
              <p className="mt-6 max-w-md text-lg leading-8 text-neutral-400">
                Thread helps a community move from remembering what happened to knowing what to do next.
              </p>
            </div>
            <div className="lg:col-span-8">
              {capabilityRows.map(([title, description], index) => (
                <div key={title} className="grid gap-4 border-t border-neutral-800 py-6 sm:grid-cols-[3rem_minmax(0,1fr)_minmax(0,1fr)] sm:gap-6">
                  <span className="text-sm text-neutral-600">0{index + 1}</span>
                  <h3 className="text-lg text-neutral-100">{title}</h3>
                  <p className="text-sm leading-6 text-neutral-500">{description}</p>
                </div>
              ))}
              <div className="border-t border-neutral-800" />
            </div>
          </div>
        </section>

        <section className="relative overflow-hidden px-5 py-24 sm:px-8 sm:py-32 lg:px-12">
          <ThreadLight className="pointer-events-none absolute inset-0 h-full w-full opacity-55" />
          <div className="mx-auto max-w-7xl">
            <div className="relative border-y border-neutral-800 py-12 sm:py-16">
              <div className="flex items-center gap-2 text-sm text-neutral-500">
                <Sparkles className="h-4 w-4" aria-hidden="true" />
                ThreadAgent
              </div>
              <h2 className="mt-6 max-w-4xl text-4xl font-medium leading-tight text-neutral-100 sm:text-6xl">
                Bring the agent into the conversation.
              </h2>
              <div className="mt-10 flex flex-wrap items-center gap-x-6 gap-y-4">
                <button onClick={onOpenWorkspace} className="inline-flex items-center gap-2 text-base text-neutral-100 transition-transform hover:translate-x-1">
                  Open workspace
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </button>
                <span className="inline-flex items-center gap-2 text-sm text-neutral-500">
                  <Check className="h-4 w-4" aria-hidden="true" />
                  Discord, Slack, Telegram, GitHub, and web
                </span>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-neutral-800 px-5 py-6 text-sm text-neutral-600 sm:px-8 lg:px-12">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
          <span>ThreadAgent</span>
          <span>Context where the work happens.</span>
        </div>
      </footer>
    </div>
  );
};
