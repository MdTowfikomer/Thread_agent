import React, { useState, useEffect } from 'react';
import { Navbar } from '../components/Navbar';
import { Sidebar } from '../components/Sidebar';
import { ChatArea } from '../components/ChatArea';
import { AuthModal } from '../components/AuthModal';
import { getWorkspace, getMemories, getConnections, getReviewItems, validateSession, logoutSession, clearAuthToken, ApiError } from '../api';
import { OrganizationWorkspace, MemoryItem, ConnectionsData, ReviewData, ConnectionItem } from '../types';
import { AlertTriangle, KeyRound } from 'lucide-react';

type WorkspaceTab = 'chat' | 'timeline' | 'connections' | 'review' | 'settings';

interface WorkspacePageProps {
  onNavigate: (route: string) => void;
  currentRoute: string;
}

export const WorkspacePage: React.FC<WorkspacePageProps> = ({ onNavigate, currentRoute }) => {
  const [workspace, setWorkspace] = useState<OrganizationWorkspace | null>(null);
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('chat');
  const [selectedPromptQuery, setSelectedPromptQuery] = useState<string | null>(null);
  const [activeSourceFilter, setActiveSourceFilter] = useState<string>('all');

  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [connections, setConnections] = useState<ConnectionsData | null>(null);
  const [reviewData, setReviewData] = useState<ReviewData | null>(null);

  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);
  const [authErrorDetail, setAuthErrorDetail] = useState<string | undefined>(undefined);
  const [loadingWorkspace, setLoadingWorkspace] = useState<boolean>(true);

  const loadWorkspaceData = async () => {
    setLoadingWorkspace(true);
    setAuthErrorDetail(undefined);

    const session = await validateSession();
    if (!session) {
      setIsAuthenticated(false);
      setAuthErrorDetail('Session is unauthenticated or invalid (401).');
      setLoadingWorkspace(false);
      return;
    }

    setIsAuthenticated(true);
    try {
      const ws = await getWorkspace();
      setWorkspace(ws);

      Promise.all([
        getMemories().catch(() => []),
        getConnections().catch(() => null),
        getReviewItems().catch(() => null),
      ]).then(([m, c, r]) => {
        setMemories(m);
        setConnections(c);
        setReviewData(r);
      });
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 401) {
        setIsAuthenticated(false);
        setAuthErrorDetail('Session is unauthenticated or invalid (401).');
      } else {
        setAuthErrorDetail(err.message || 'Error connecting to workspace backend.');
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
    setReviewData(null);
  };

  const handleUnauthorized = () => {
    setIsAuthenticated(false);
    setAuthErrorDetail('Your session token has expired or is invalid (401).');
    setIsAuthModalOpen(true);
  };

  const tabs: [WorkspaceTab, string][] = [
    ['chat', 'chat'],
    ['timeline', 'timeline'],
    ['connections', 'connections'],
    ['review', 'review_queue'],
    ['settings', 'settings'],
  ];

  return (
    <div className="min-h-screen flex flex-col bg-[#0a0a0a] text-neutral-200 font-sans">
      {/* Top Navbar */}
      <Navbar
        workspaceName={workspace?.name || 'GDG MCET'}
        isAuthenticated={isAuthenticated}
        onNavigate={onNavigate}
        currentRoute={currentRoute}
        onOpenAuthModal={() => setIsAuthModalOpen(true)}
        onSignOut={handleSignOut}
        userLabel={isAuthenticated ? 'authenticated' : 'signed_out'}
      />

      {/* Workspace Sub-Navigation Bar */}
      <nav className="border-b border-neutral-800 bg-[#0a0a0a] px-6 py-2 flex items-center gap-4 overflow-x-auto shrink-0 font-mono text-xs">
        {tabs.map(([tabId, label]) => {
          const isActive = activeTab === tabId;
          return (
            <button
              key={tabId}
              onClick={() => setActiveTab(tabId)}
              className={`py-1 transition-colors cursor-pointer whitespace-nowrap ${
                isActive
                  ? 'text-neutral-100 font-bold border-b border-neutral-100'
                  : 'text-neutral-500 hover:text-neutral-300'
              }`}
            >
              [{label}]
            </button>
          );
        })}
      </nav>

      {/* Main Workspace Surface */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* Signed-Out Banner */}
        {!isAuthenticated && (
          <div className="absolute top-0 left-0 right-0 z-30 bg-amber-950/90 text-amber-200 border-b border-amber-800/80 px-4 py-2 flex items-center justify-between font-mono text-xs">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
              <span>Signed Out: Bearer token required. Memory queries enforce pre-retrieval security.</span>
            </div>
            <button
              onClick={() => setIsAuthModalOpen(true)}
              className="flex items-center gap-1 bg-neutral-100 text-neutral-900 px-2.5 py-1 rounded text-[11px] font-bold hover:bg-white cursor-pointer"
            >
              <KeyRound className="w-3 h-3" />
              <span>Authenticate</span>
            </button>
          </div>
        )}

        {activeTab === 'chat' ? (
          <div className="flex-1 flex w-full h-full overflow-hidden">
            <Sidebar
              workspace={workspace}
              onSelectPrompt={(p) => setSelectedPromptQuery(p)}
              activeSourceFilter={activeSourceFilter}
              onSelectSourceFilter={(s) => setActiveSourceFilter(s)}
            />
            <ChatArea
              workspaceName={workspace?.name || 'GDG MCET'}
              onSelectPromptQuery={selectedPromptQuery}
              onClearSelectedPrompt={() => setSelectedPromptQuery(null)}
              onUnauthorized={handleUnauthorized}
              activeSourceFilter={activeSourceFilter}
            />
          </div>
        ) : (
          <main className="flex-1 overflow-y-auto p-6 max-w-5xl mx-auto w-full space-y-6 font-mono text-xs">
            {activeTab === 'timeline' && <TimelineView memories={memories} />}
            {activeTab === 'connections' && <ConnectionsView data={connections} />}
            {activeTab === 'review' && <ReviewView data={reviewData} isAuthenticated={isAuthenticated} />}
            {activeTab === 'settings' && <SettingsView workspace={workspace} />}
          </main>
        )}
      </div>

      {/* Auth Modal */}
      <AuthModal
        isOpen={isAuthModalOpen}
        onClose={() => setIsAuthModalOpen(false)}
        onAuthenticated={() => {
          setIsAuthModalOpen(false);
          loadWorkspaceData();
        }}
        errorDetail={authErrorDetail}
      />
    </div>
  );
};

function Heading({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <header className="pb-3 border-b border-neutral-800">
      <h1 className="text-sm font-bold uppercase tracking-wider text-neutral-100">// {title}</h1>
      <p className="text-xs text-neutral-500 font-sans mt-0.5">{subtitle}</p>
    </header>
  );
}

function TimelineView({ memories }: { memories: MemoryItem[] }) {
  return (
    <>
      <Heading
        title="Source Timeline"
        subtitle="Canonical institutional records retrieved for your verified security level."
      />
      <div className="space-y-4">
        {memories.length === 0 ? (
          <div className="p-8 border border-neutral-800 text-center text-xs text-neutral-500 font-sans">
            No authorized records available or authenticated session required.
          </div>
        ) : (
          memories
            .slice()
            .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
            .map((item) => (
              <article key={item.id} className="pb-4 border-b border-neutral-800 space-y-2">
                <div className="flex items-center justify-between text-[11px] text-neutral-500">
                  <span className="font-bold text-neutral-200">
                    [{item.source?.toUpperCase()}] {item.title || 'Record'}
                  </span>
                  <span>{new Date(item.timestamp).toLocaleString()}</span>
                </div>
                <p className="text-xs text-neutral-300 font-sans leading-relaxed">{item.content}</p>
                <div className="flex items-center justify-between text-[10px] text-neutral-500">
                  <span>Author: {item.author}</span>
                  <span>Scope: {item.permission}</span>
                </div>
              </article>
            ))
        )}
      </div>
    </>
  );
}

function ConnectionsView({ data }: { data: ConnectionsData | null }) {
  const platforms = ['discord', 'slack', 'telegram', 'github'] as const;
  const connData = data?.connections || { github: [], discord: [], telegram: [], slack: [] };

  return (
    <>
      <Heading
        title="Server-Bound Connections"
        subtitle="Active platform bindings enforcing authoritative organizational boundaries."
      />
      <div className="grid md:grid-cols-2 gap-6">
        {platforms.map((plat) => {
          const items: ConnectionItem[] = connData[plat] || [];
          return (
            <div key={plat} className="pb-4 border-b border-neutral-800 space-y-2">
              <div className="font-bold text-xs uppercase text-neutral-100 flex items-center justify-between">
                <span>// {plat} Integration</span>
                <span className="text-[10px] text-neutral-500">{items.length} Bound</span>
              </div>
              <div className="space-y-2 pt-1 font-mono text-xs">
                {items.length === 0 ? (
                  <p className="text-neutral-500 italic text-[11px]">No active bindings.</p>
                ) : (
                  items.map((item) => (
                    <div key={item.id} className="p-2 border border-neutral-800 bg-[#121212] space-y-1">
                      <div className="font-bold text-neutral-200">{item.label}</div>
                      <div className="text-[10px] text-neutral-500">ID: {item.id}</div>
                      {item.channels && item.channels.length > 0 && (
                        <div className="text-[10px] text-neutral-400">Channels: {item.channels.join(', ')}</div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}

function ReviewView({ data, isAuthenticated }: { data: ReviewData | null; isAuthenticated: boolean }) {
  return (
    <>
      <Heading
        title="Quarantine & Identity Review"
        subtitle="Organizer decisions for quarantined internal imports and unverified identity links."
      />
      {!isAuthenticated ? (
        <div className="p-4 border border-amber-800 bg-amber-950/20 text-amber-300 text-xs font-sans">
          <span className="font-bold block uppercase tracking-wider font-mono text-[10px] mb-1">
            [Unauthorized] Review Access Required
          </span>
          <p>Review access requires an authenticated organizer Bearer token.</p>
        </div>
      ) : (
        <div className="grid md:grid-cols-2 gap-6">
          <div className="space-y-3">
            <h3 className="font-bold text-xs uppercase text-neutral-100 border-b border-neutral-800 pb-2">
              // Quarantine Queue ({data?.quarantine?.length || 0})
            </h3>
            <div className="space-y-2 text-xs">
              {!data?.quarantine || data.quarantine.length === 0 ? (
                <p className="text-neutral-500 italic text-[11px]">No items in quarantine.</p>
              ) : (
                data.quarantine.map((q) => (
                  <div key={q.id} className="p-3 border border-neutral-800 bg-[#121212] space-y-1 font-mono text-[11px]">
                    <span className="font-bold text-neutral-200">{q.title}</span>
                    <p className="text-neutral-400 font-sans text-xs">{q.content}</p>
                    <span className="text-[10px] text-neutral-500 block">Author: {q.author}</span>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="space-y-3">
            <h3 className="font-bold text-xs uppercase text-neutral-100 border-b border-neutral-800 pb-2">
              // Identity Verification Links ({data?.identity_links?.length || 0})
            </h3>
            <div className="space-y-2 text-xs">
              {!data?.identity_links || data.identity_links.length === 0 ? (
                <p className="text-neutral-500 italic text-[11px]">No pending identity verification links.</p>
              ) : (
                data.identity_links.map((link, idx) => (
                  <div key={idx} className="p-3 border border-neutral-800 bg-[#121212] space-y-1 font-mono text-[11px]">
                    <span className="font-bold text-neutral-200">[{link.channel_type?.toUpperCase()}]</span>
                    <div className="text-neutral-400">Account ID: {link.account_id}</div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function SettingsView({ workspace }: { workspace: OrganizationWorkspace | null }) {
  return (
    <>
      <Heading
        title="Agent Operational Settings"
        subtitle="System parameters and runtime configuration shell."
      />
      <div className="grid md:grid-cols-2 gap-6 text-xs font-mono">
        <div className="p-4 border border-neutral-800 bg-[#121212] space-y-2">
          <h3 className="font-bold text-neutral-100 uppercase border-b border-neutral-800 pb-2">
            // Active Workspace Config
          </h3>
          <div className="space-y-1 text-[11px] text-neutral-400">
            <div className="flex justify-between">
              <span>Workspace ID:</span>
              <span className="text-neutral-200 font-bold">{workspace?.id || 'gdg_mcet'}</span>
            </div>
            <div className="flex justify-between">
              <span>Workspace Name:</span>
              <span className="text-neutral-200 font-bold">{workspace?.name || 'GDG MCET'}</span>
            </div>
            <div className="flex justify-between">
              <span>Default Role:</span>
              <span className="text-neutral-200 font-bold">{workspace?.default_role_id || 'organizer_lead'}</span>
            </div>
          </div>
        </div>

        <div className="p-4 border border-neutral-800 bg-[#121212] space-y-2">
          <h3 className="font-bold text-neutral-100 uppercase border-b border-neutral-800 pb-2">
            // Engine Parameters
          </h3>
          <div className="space-y-1 text-[11px] text-neutral-400">
            <div className="flex justify-between">
              <span>Vector Engine:</span>
              <span className="text-neutral-200 font-bold">Supabase pgvector / RRF</span>
            </div>
            <div className="flex justify-between">
              <span>Security Scope:</span>
              <span className="text-neutral-200 font-bold">Pre-Retrieval ACL</span>
            </div>
            <div className="flex justify-between">
              <span>Gateway Lock:</span>
              <span className="text-neutral-200 font-bold">PostgreSQL Session Lock</span>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
