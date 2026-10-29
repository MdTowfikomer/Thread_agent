import { ChatResponse, ConnectionsData, MemoryItem, OrganizationWorkspace, ReviewData } from './types';

const API_BASE = '/api';

export class ApiError extends Error {
  status: number;
  traceId?: string;
  conversationId?: string;
  constructor(status: number, message: string, traceId?: string, conversationId?: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
    this.traceId = traceId;
    this.conversationId = conversationId;
  }
}

export function getAuthToken(): string | null {
  // Production auth boundary: browser storage must not accept or store pasted JWTs
  return null;
}

export function setAuthToken(_token: string, _remember: boolean = true) {
  // Production auth boundary: no-op, pasted JWTs are not accepted or stored in browser storage
}

export function clearAuthToken() {
  localStorage.removeItem('thread_token');
  sessionStorage.removeItem('thread_token');
}

export function getAuthHeaders(): Record<string, string> {
  return {};
}

export interface SessionInfo {
  authenticated: boolean;
  user_id: string;
  organization_id: string;
  is_guest: boolean;
  role_id: string;
  allowed_scopes: string[];
  user_permission: string;
}

export async function validateSession(): Promise<SessionInfo | null> {
  try {
    const res = await fetch(`${API_BASE}/session`, {
      headers: getAuthHeaders(),
      credentials: 'include',
    });
    if (!res.ok) {
      return null;
    }
    return await res.json();
  } catch {
    return null;
  }
}

export async function startDemoSession(): Promise<boolean> {
  try {
    await v2Request('/auth/logout', { method: 'POST' });
    const res = await fetch(`${API_BASE}/session/demo`, {
      method: 'POST',
      credentials: 'include',
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function logoutSession(): Promise<boolean> {
  try {
    await v2Request('/auth/logout', { method: 'POST' });
    const res = await fetch(`${API_BASE}/session/logout`, {
      method: 'POST',
      credentials: 'include'
    });
    return res.ok;
  } catch {
    return false;
  }
}

export type AppRole = 'owner' | 'admin' | 'member';
export interface WorkspaceSummary { id: string; name: string; description: string; role: AppRole }
export interface AccountInfo {
  user: { id: string; name: string; email: string };
  active_organization_id: string | null;
  organizations: WorkspaceSummary[];
}
export interface WorkspaceMember { id: string; name: string; email: string; role: AppRole }
export interface WorkspaceDetails extends WorkspaceSummary {
  default_agent_name: string;
  system_prompt: string;
  configured_roles: import('./types').RoleAgent[];
}

export async function v2Request<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/v2${path}`, {
    ...options, credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof data.detail === 'string' ? data.detail : 'Check the form fields and try again.';
    throw new ApiError(response.status, message);
  }
  return data as T;
}

export const getAccount = () => v2Request<AccountInfo>('/auth/me');
export const createWorkspace = (name: string, description = '') => v2Request<WorkspaceSummary>('/organizations', { method: 'POST', body: JSON.stringify({ name, description }) });
export const switchWorkspace = (id: string) => v2Request(`/organizations/${encodeURIComponent(id)}/switch`, { method: 'POST' });

export async function sendChatMessage(query: string): Promise<ChatResponse> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...getAuthHeaders(),
  };

  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers,
    credentials: 'include',
    body: JSON.stringify({ query })
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Network error' }));
    throw new ApiError(res.status, err.detail || `Server error (${res.status})`, res.headers.get('X-Thread-Trace-Id') || undefined, res.headers.get('X-Thread-Conversation-Id') || undefined);
  }

  return res.json();
}


export type SSEEvent =
  | { type: 'stage'; step: string; label: string; status: 'running' | 'completed' | 'failed'; message?: string; intent?: string; role?: string; count?: number; sufficient?: boolean }
  | { type: 'tool_call'; step: string; tool: string; label: string; status: 'running' | 'completed' | 'failed'; message?: string; args?: string; count?: number }
  | { type: 'token'; text: string }
  | { type: 'complete'; response: ChatResponse }
  | { type: 'error'; error: string; status?: number };

export async function sendChatMessageStream(
  query: string,
  onEvent: (event: SSEEvent) => void
): Promise<ChatResponse> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...getAuthHeaders(),
  };

  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers,
    credentials: 'include',
    body: JSON.stringify({ query })
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Network error' }));
    throw new ApiError(res.status, err.detail || `Server error (${res.status})`, res.headers.get('X-Thread-Trace-Id') || undefined, res.headers.get('X-Thread-Conversation-Id') || undefined);
  }

  const reader = res.body?.getReader();
  if (!reader) {
    throw new ApiError(500, 'Streaming is unsupported by this browser.');
  }

  const decoder = new TextDecoder();
  let buffer = '';
  let finalResponse: ChatResponse | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split('\n\n');
    buffer = lines.pop() || '';

    for (const chunk of lines) {
      const trimmed = chunk.trim();
      if (!trimmed.startsWith('data:')) continue;
      const jsonStr = trimmed.slice(5).trim();
      if (!jsonStr) continue;
      try {
        const parsed = JSON.parse(jsonStr) as SSEEvent;
        if (parsed.type === 'complete') {
          finalResponse = parsed.response;
        } else if (parsed.type === 'error') {
          throw new ApiError(parsed.status || 500, parsed.error);
        }
        onEvent(parsed);
      } catch (e) {
        if (e instanceof ApiError) throw e;
      }
    }
  }

  if (finalResponse) {
    return finalResponse;
  }
  throw new ApiError(500, 'Incomplete stream from server.');
}

export async function getWorkspace(): Promise<OrganizationWorkspace> {
  const res = await fetch(`${API_BASE}/workspace`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to fetch workspace' }));
    throw new ApiError(res.status, err.detail || 'Failed to fetch workspace');
  }
  return res.json();
}

export async function getMemories(): Promise<MemoryItem[]> {
  const res = await fetch(`${API_BASE}/memories`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to fetch memories' }));
    throw new ApiError(res.status, err.detail || 'Failed to fetch memories');
  }
  const data = await res.json();
  return data.memories || [];
}

export async function getConnections(): Promise<ConnectionsData> {
  const res = await fetch(`${API_BASE}/connections`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to fetch connections' }));
    throw new ApiError(res.status, err.detail || 'Failed to fetch connections');
  }
  return res.json();
}

export async function getReviewItems(): Promise<ReviewData> {
  const res = await fetch(`${API_BASE}/review`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to fetch review items' }));
    throw new ApiError(res.status, err.detail || 'Failed to fetch review items');
  }
  return res.json();
}
