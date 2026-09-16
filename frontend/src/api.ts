import { ChatResponse, ConnectionsData, MemoryItem, OrganizationWorkspace, ReviewData } from './types';

const API_BASE = '/api';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
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

export async function loginSession(userId: string = "demo_organizer"): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/session/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ user_id: userId, organization_id: 'gdg_mcet' })
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function logoutSession(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/session/logout`, {
      method: 'POST',
      credentials: 'include'
    });
    return res.ok;
  } catch {
    return false;
  }
}

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
    throw new ApiError(res.status, err.detail || `Server error (${res.status})`);
  }

  return res.json();
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
