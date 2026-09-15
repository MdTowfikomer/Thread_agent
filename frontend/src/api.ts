import { OrganizationWorkspace, UserRole } from './types';

const API_BASE = '/api';

export async function sendChatMessage(
  query: string,
  organizationId: string = 'gdg_mcet',
  userRole: UserRole = 'organizer'
): Promise<{
  query: string;
  answer: string;
  role_agent: any;
  citations: any[];
  confidence_score: number;
  trace: any[];
  organization_id: string;
}> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      organization_id: organizationId,
      user_role: userRole
    })
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Network error' }));
    throw new Error(err.detail || `Server error: ${res.status}`);
  }

  return res.json();
}

export async function getWorkspace(organizationId: string = 'gdg_mcet'): Promise<OrganizationWorkspace> {
  const res = await fetch(`${API_BASE}/workspace?organization_id=${organizationId}`);
  if (!res.ok) throw new Error('Failed to fetch workspace');
  return res.json();
}

export async function getMemories(organizationId: string = 'gdg_mcet'): Promise<any[]> {
  const res = await fetch(`${API_BASE}/memories?organization_id=${organizationId}`);
  if (!res.ok) throw new Error('Failed to fetch memories');
  const data = await res.json();
  return data.memories || [];
}

export async function getConnections(organizationId: string = 'gdg_mcet'): Promise<any> {
  const res = await fetch(`${API_BASE}/connections?organization_id=${organizationId}`);
  if (!res.ok) throw new Error('Failed to fetch connections');
  return res.json();
}

export async function getReviewItems(organizationId: string = 'gdg_mcet'): Promise<any> {
  const res = await fetch(`${API_BASE}/review?organization_id=${organizationId}`);
  if (!res.ok) throw new Error('Failed to fetch review items');
  return res.json();
}
