export interface Citation {
  item_id: string;
  source: string;
  author: string;
  title?: string;
  snippet: string;
  permission: string;
  source_uri?: string;
  relevance_score: number;
}

export interface AgentTraceStep {
  step: string;
  agent_id: string;
  agent_name: string;
  status: string;
  message: string;
  timestamp: string;
}

export interface RoleAgent {
  id: string;
  name: string;
  role: string;
  department: string;
  style: string;
  avatar: string;
  expertise: string[];
}

export interface OrganizationWorkspace {
  id: string;
  name: string;
  description: string;
  default_role_id: string;
  roles: RoleAgent[];
}

export interface ChatResponse {
  query: string;
  answer: string;
  role_agent?: RoleAgent;
  citations: Citation[];
  confidence_score: number;
  retrieval_receipt_id?: string;
  receipt?: {
    receipt_id: string;
    organization_id: string;
    allowed_scopes: string[];
    candidates_retrieved: number;
    candidates_after_acl: number;
  };
  sufficient_evidence?: boolean;
  trace: AgentTraceStep[];
  organization_id?: string;
}

export interface MemoryItem {
  id: string;
  source: string;
  source_uri?: string;
  author: string;
  author_role?: string;
  title?: string;
  content: string;
  permission: string;
  tags?: string[];
  entities?: string[];
  provenance?: Record<string, any>;
  timestamp: string;
}

export interface ConnectionItem {
  id: string;
  label: string;
  status: string;
  channels?: string[];
}

export interface ConnectionsData {
  organization_id: string;
  connections: {
    github: ConnectionItem[];
    discord: ConnectionItem[];
    telegram: ConnectionItem[];
    slack: ConnectionItem[];
  };
}

export interface ReviewData {
  organization_id: string;
  quarantine: Array<{
    id: string;
    source: string;
    title: string;
    author: string;
    content: string;
    provenance?: Record<string, any>;
  }>;
  identity_links: Array<{
    organization_id: string;
    channel_type: string;
    account_id: string;
    is_verified: boolean;
    is_active: boolean;
  }>;
}

export interface AuthSession {
  token: string | null;
  userId?: string;
  organizationId?: string;
  isAuthenticated: boolean;
  status: 'authenticated' | 'unauthenticated' | 'loading' | 'error';
  errorDetail?: string;
}
