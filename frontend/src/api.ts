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
  return localStorage.getItem('thread_token') || sessionStorage.getItem('thread_token');
}

export function setAuthToken(token: string, remember: boolean = true) {
  if (remember) {
    localStorage.setItem('thread_token', token);
  } else {
    sessionStorage.setItem('thread_token', token);
  }
}

export function clearAuthToken() {
  localStorage.removeItem('thread_token');
  sessionStorage.removeItem('thread_token');
}

export function getAuthHeaders(): Record<string, string> {
  const token = getAuthToken();
  return token ? { 'Authorization': `Bearer ${token}` } : {};
}

export async function sendChatMessage(query: string): Promise<ChatResponse> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...getAuthHeaders(),
  };

  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers,
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
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to fetch review items' }));
    throw new ApiError(res.status, err.detail || 'Failed to fetch review items');
  }
  return res.json();
}
