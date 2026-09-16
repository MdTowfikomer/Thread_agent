import React, { useEffect, useState } from 'react';
import { AlertTriangle, ArrowRight, Link2, MessageSquareText, Network } from 'lucide-react';
import { ChatArea } from '../components/ChatArea';
import { demoPlatformLinks } from '../demoLinks';
import { Navbar } from '../components/Navbar';
import { Sidebar } from '../components/Sidebar';
import { ApiError, clearAuthToken, getConnections, getMemories, getWorkspace, logoutSession, validateSession } from '../api';
import { ConnectionItem, ConnectionsData, MemoryItem, OrganizationWorkspace } from '../types';

type WorkspaceTab = 'chat' | 'timeline' | 'connections';

interface WorkspacePageProps {
  onNavigate: (route: string) => void;
  currentRoute: string;
}

export const WorkspacePage: React.FC<WorkspacePageProps> = ({ onNavigate, currentRoute }) => {
  const [workspace, setWorkspace] = useState<OrganizationWorkspace | null>(null);
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('chat');
  const [selectedPromptQuery, setSelectedPromptQuery] = useState<string | null>(null);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [connections, setConnections] = useState<ConnectionsData | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loadingWorkspace, setLoadingWorkspace] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadWorkspaceData = async () => {
    setLoadingWorkspace(true);
    setError(null);
    const session = await validateSession();
    if (!session) {
      setIsAuthenticated(false);
      setLoadingWorkspace(false);
      return;
    }

    setIsAuthenticated(true);
    try {
      const loadedWorkspace = await getWorkspace();
      setWorkspace(loadedWorkspace);
      const [loadedMemories, loadedConnections] = await Promise.all([
        getMemories().catch(() => []),
        getConnections().catch(() => null),
      ]);
      setMemories(loadedMemories);
      setConnections(loadedConnections);
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 401) {
        setIsAuthenticated(false);
      } else {
        setError(requestError instanceof Error ? requestError.message : 'Thread could not load this workspace.');
      }
    } finally {
      setLoadingWorkspace(false);
    }
  };

  useEffect(() => {
    loadWorkspaceData();
  }, []);

  const handleSignOut = async () => {
    await logoutSession();
    clearAuthToken();
    setIsAuthenticated(false);
    setWorkspace(null);
    setMemories([]);
    setConnections(null);
    onNavigate('/auth');
  };

  const connectedCount = Object.values(connections?.connections || {}).flat().length;
  const tabs: Array<{ id: WorkspaceTab; label: string; icon: React.ElementType }> = [
    { id: 'chat', label: 'Ask Thread', icon: MessageSquareText },
    { id: 'timeline', label: 'Source timeline', icon: Network },
    { id: 'connections', label: 'Connections', icon: Link2 },
  ];

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-neutral-200">
      <Navbar
        workspaceName={workspace?.name || 'GDG MCET'}
        isAuthenticated={isAuthenticated}
        onNavigate={onNavigate}
        currentRoute={currentRoute}
        onOpenAuthModal={() => onNavigate('/auth')}
        onSignOut={handleSignOut}
        userLabel={isAuthenticated ? 'Demo Viewer' : 'Signed out'}
      />

      {!isAuthenticated && !loadingWorkspace ? (
        <main className="mx-auto flex min-h-[calc(100svh-4rem)] max-w-2xl items-center px-5 sm:px-8">
          <div className="border-y border-neutral-800 py-10">
            <AlertTriangle className="h-5 w-5 text-neutral-400" aria-hidden="true" />
            <h1 className="mt-5 text-3xl font-medium text-neutral-100">Open the live demo to continue.</h1>
            <p className="mt-4 max-w-lg text-lg leading-8 text-neutral-400">The workspace needs a public-only demo session before it can show connected community context.</p>
            <button onClick={() => onNavigate('/auth')} className="mt-8 inline-flex items-center gap-2 text-sm text-neutral-100 transition-transform hover:translate-x-1">
              Open demo workspace
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </main>
      ) : (
        <>
          <nav className="border-b border-neutral-800 px-5 sm:px-8" aria-label="Workspace views">
            <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-5 overflow-x-auto">
              <div className="flex min-w-max items-center gap-1">
                {tabs.map(({ id, label, icon: Icon }) => (
                  <button
                    key={id}
                    onClick={() => setActiveTab(id)}
                    className={`inline-flex h-14 items-center gap-2 border-b px-3 text-sm transition-colors ${activeTab === id ? 'border-neutral-100 text-neutral-100' : 'border-transparent text-neutral-500 hover:text-neutral-200'}`}
                  >
                    <Icon className="h-4 w-4" aria-hidden="true" />
                    {label}
                  </button>
                ))}
              </div>
              <span className="hidden shrink-0 text-sm text-neutral-500 md:block">{connectedCount} connected source{connectedCount === 1 ? '' : 's'}</span>
            </div>
          </nav>

          {error && <div className="border-b border-neutral-800 px-5 py-3 text-sm text-neutral-400 sm:px-8">{error}</div>}
          {loadingWorkspace ? (
            <main className="grid min-h-[calc(100svh-7.5rem)] place-items-center text-sm text-neutral-500">Loading workspace</main>
          ) : activeTab === 'chat' ? (
            <div className="flex min-h-0">
              <Sidebar
                workspace={workspace}
                onSelectPrompt={(prompt) => setSelectedPromptQuery(prompt)}
                activeSourceFilter="all"
                onSelectSourceFilter={() => undefined}
              />
              <ChatArea
                workspaceName={workspace?.name || 'GDG MCET'}
                onSelectPromptQuery={selectedPromptQuery}
                onClearSelectedPrompt={() => setSelectedPromptQuery(null)}
                onUnauthorized={() => setIsAuthenticated(false)}
              />
            </div>
          ) : (
            <main className="mx-auto w-full max-w-6xl px-5 py-10 sm:px-8 lg:px-12">
              {activeTab === 'timeline' && <TimelineView memories={memories} />}
              {activeTab === 'connections' && <ConnectionsView data={connections} />}
            </main>
          )}
        </>
      )}
    </div>
  );
};

function TimelineView({ memories }: { memories: MemoryItem[] }) {
  return (
    <section>
      <p className="text-sm text-neutral-500">Community memory</p>
      <h1 className="mt-2 text-3xl font-medium text-neutral-100 sm:text-4xl">Source timeline</h1>
      <p className="mt-4 max-w-2xl text-lg leading-8 text-neutral-400">Public records currently available to this demo session.</p>
      <div className="mt-10 divide-y divide-neutral-800 border-y border-neutral-800">
        {memories.length === 0 ? (
          <p className="py-10 text-neutral-500">No public records are available yet.</p>
        ) : memories.slice().sort((a, b) => b.timestamp.localeCompare(a.timestamp)).map((item) => (
          <article key={item.id} className="grid gap-4 py-6 md:grid-cols-[9rem_minmax(0,1fr)_auto] md:gap-8">
            <div className="text-sm text-neutral-500">
              <p>{item.source}</p>
              <p className="mt-1 text-xs">{new Date(item.timestamp).toLocaleDateString()}</p>
            </div>
            <div>
              <h2 className="text-lg font-medium text-neutral-100">{item.title || 'Community record'}</h2>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-neutral-400">{item.content}</p>
            </div>
            <span className="text-xs text-neutral-600">{item.author}</span>
          </article>
        ))}
      </div>
    </section>
  );
}

function ConnectionsView({ data }: { data: ConnectionsData | null }) {
  const platforms = ['discord', 'slack', 'telegram', 'github'] as const;
  const connectionData = data?.connections || { github: [], discord: [], telegram: [], slack: [] };

  return (
    <section>
      <p className="text-sm text-neutral-500">Live integrations</p>
      <h1 className="mt-2 text-3xl font-medium text-neutral-100 sm:text-4xl">Connected sources</h1>
      <p className="mt-4 max-w-2xl text-lg leading-8 text-neutral-400">Thread is already connected to the community platforms shown below. No setup is required for this demo.</p>
      <div className="mt-10 divide-y divide-neutral-800 border-y border-neutral-800">
        {platforms.map((platform) => <ConnectionRow key={platform} platform={platform} items={connectionData[platform] || []} />)}
      </div>
    </section>
  );
}

function ConnectionRow({ platform, items }: { platform: string; items: ConnectionItem[] }) {
  const testUrl = platform === 'discord'
    ? demoPlatformLinks.discord
    : platform === 'slack'
      ? demoPlatformLinks.slack
      : platform === 'telegram'
        ? demoPlatformLinks.telegram
        : undefined;
  const testLabel = platform === 'telegram' ? 'Message bot' : 'Open test channel';

  return (
    <div className="grid gap-4 py-6 sm:grid-cols-[10rem_minmax(0,1fr)] sm:gap-8">
      <div>
        <p className="text-lg capitalize text-neutral-100">{platform}</p>
        <p className="mt-1 text-sm text-neutral-500">{items.length ? 'Connected' : 'Not connected'}</p>
      </div>
      <div className="space-y-3">
        {items.length ? items.map((item) => <p key={item.id} className="text-sm text-neutral-400">{item.label}{item.channels?.length ? ` · ${item.channels.length} channel${item.channels.length === 1 ? '' : 's'}` : ''}</p>) : <p className="text-sm text-neutral-600">No active binding is exposed in this session.</p>}
        {testUrl && <a href={testUrl} target="_blank" rel="noreferrer" className="inline-flex w-fit border-b border-neutral-600 pb-1 text-sm text-neutral-200 transition-colors hover:border-neutral-100">{testLabel}</a>}
      </div>
    </div>
  );
}
