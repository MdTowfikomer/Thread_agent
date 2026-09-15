import React, { useEffect, useState } from 'react';
import { CheckCircle2, Clock3, List, MessageSquare, Network, ShieldAlert } from 'lucide-react';
import { Navbar } from './components/Navbar';
import { Sidebar } from './components/Sidebar';
import { ChatArea } from './components/ChatArea';
import { OrganizationWorkspace, ChatMessage, UserRole } from './types';
import { getConnections, getMemories, getReviewItems, getWorkspace, sendChatMessage } from './api';

type Screen = 'chat' | 'timeline' | 'connections' | 'review';

export function App() {
  const [workspace, setWorkspace] = useState<OrganizationWorkspace | null>(null);
  const [userRole, setUserRole] = useState<UserRole>('organizer');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [screen, setScreen] = useState<Screen>('chat');
  const [connections, setConnections] = useState<any>({});
  const [memories, setMemories] = useState<any[]>([]);
  const [review, setReview] = useState<any>({ quarantine: [], identity_links: [] });

  useEffect(() => {
    getWorkspace().then(setWorkspace).catch(console.error);
    Promise.all([getConnections(), getMemories(), getReviewItems()])
      .then(([c, m, r]) => { setConnections(c.connections || {}); setMemories(m); setReview(r); })
      .catch(console.error);
  }, []);

  const handleSendMessage = async (query: string) => {
    setMessages(prev => [...prev, { id: `user-${Date.now()}`, role: 'user', content: query, timestamp: new Date().toLocaleTimeString() }]);
    setLoading(true);
    try {
      const response = await sendChatMessage(query, workspace?.id || 'gdg_mcet', userRole);
      setMessages(prev => [...prev, { id: `assistant-${Date.now()}`, role: 'assistant', content: response.answer, timestamp: new Date().toLocaleTimeString(), role_agent: response.role_agent, citations: response.citations, confidence_score: response.confidence_score, trace: response.trace }]);
    } catch (err: any) {
      setMessages(prev => [...prev, { id: `error-${Date.now()}`, role: 'assistant', content: err.message || 'Unable to retrieve evidence.', timestamp: new Date().toLocaleTimeString() }]);
    } finally { setLoading(false); }
  };

  const tabs: [Screen, string, React.ElementType][] = [['chat', 'Chat', MessageSquare], ['timeline', 'Source timeline', List], ['connections', 'Connections', Network], ['review', 'Review', ShieldAlert]];
  return <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100">
    <Navbar workspaceName={workspace?.name || 'GDG MCET'} userRole={userRole} onUserRoleChange={setUserRole} />
    <nav className="border-b border-slate-800 bg-slate-950 px-4 py-2 flex gap-2 overflow-x-auto">
      {tabs.map(([id, label, Icon]) => <button key={id} onClick={() => setScreen(id)} className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold whitespace-nowrap ${screen === id ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:bg-slate-900'}`}><Icon className="w-4 h-4" />{label}</button>)}
    </nav>
    <div className="flex-1 flex overflow-hidden">
      {screen === 'chat' ? <><Sidebar workspace={workspace} onSelectPrompt={handleSendMessage} userRole={userRole} /><ChatArea messages={messages} loading={loading} onSendMessage={handleSendMessage} workspaceName={workspace?.name || 'GDG MCET'} userRole={userRole} /></> :
        <main className="flex-1 overflow-y-auto p-6 max-w-5xl mx-auto w-full">
          {screen === 'timeline' && <Timeline memories={memories} />}
          {screen === 'connections' && <Connections data={connections} />}
          {screen === 'review' && <Review data={review} />}
        </main>}
    </div>
  </div>;
}

function Heading({ title, subtitle }: { title: string; subtitle: string }) {
  return <header className="mb-6"><h1 className="text-2xl font-extrabold">{title}</h1><p className="text-sm text-slate-400 mt-1">{subtitle}</p></header>;
}

function Timeline({ memories }: { memories: any[] }) {
  return <><Heading title="Source timeline" subtitle="Canonical records available to this workspace." /><div className="space-y-3">{memories.length === 0 ? <Empty text="No authorized records are available." /> : memories.slice().sort((a, b) => b.timestamp.localeCompare(a.timestamp)).map(item => <article key={item.id} className="rounded-xl border border-slate-800 bg-slate-900/70 p-4"><div className="flex justify-between text-xs"><b className="uppercase text-indigo-300">{item.source}</b><time className="text-slate-500">{new Date(item.timestamp).toLocaleString()}</time></div><h3 className="font-semibold mt-2">{item.title || 'Institutional record'}</h3><p className="text-sm text-slate-300 mt-1">{item.content}</p><div className="text-xs text-slate-500 mt-3">By {item.author} · <a className="text-indigo-400" href={item.source_uri} target="_blank" rel="noreferrer">source citation</a></div></article>)}</div></>;
}

function Connections({ data }: { data: any }) {
  return <><Heading title="Connection status" subtitle="Server-owned bindings reject messages outside these boundaries." /><div className="grid md:grid-cols-2 gap-4">{['github', 'discord', 'telegram', 'slack'].map(source => <article key={source} className="rounded-xl border border-slate-800 bg-slate-900/70 p-4"><h3 className="font-bold capitalize flex gap-2 items-center"><CheckCircle2 className="w-4 h-4 text-emerald-400" />{source}</h3><div className="mt-3 space-y-2">{(data[source] || []).map((item: any) => <div key={item.id} className="text-sm text-slate-300">{item.label}<span className="text-xs text-slate-500 ml-2">({item.id})</span>{item.channels?.length > 0 && <div className="text-xs text-slate-500">channels: {item.channels.join(', ')}</div>}</div>)}</div></article>)}</div></>;
}

function Review({ data }: { data: any }) {
  return <><Heading title="Quarantine and identity review" subtitle="Organizer decisions remain explicit and auditable." /><div className="grid md:grid-cols-2 gap-4"><article className="rounded-xl border border-amber-500/30 bg-slate-900/70 p-4"><h3 className="font-bold flex gap-2 items-center"><Clock3 className="w-4 h-4 text-amber-400" />Quarantine ({data.quarantine?.length || 0})</h3>{(data.quarantine || []).map((item: any) => <p key={item.id} className="text-sm text-slate-300 border-b border-slate-800 py-3">{item.title}: {item.content}</p>)}</article><article className="rounded-xl border border-cyan-500/30 bg-slate-900/70 p-4"><h3 className="font-bold flex gap-2 items-center"><ShieldAlert className="w-4 h-4 text-cyan-400" />Identity links ({data.identity_links?.length || 0})</h3>{(data.identity_links || []).map((item: any) => <p key={item.id} className="text-sm text-slate-300 border-b border-slate-800 py-3">{item.channel_type}: {item.account_id} · pending verification</p>)}</article></div></>;
}

function Empty({ text }: { text: string }) { return <div className="rounded-xl border border-dashed border-slate-700 p-8 text-center text-sm text-slate-500">{text}</div>; }

export default App;
