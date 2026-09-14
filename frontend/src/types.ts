export type UserRole = 'organizer' | 'community';

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

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  role_agent?: {
    id: string;
    name: string;
    role: string;
    avatar: string;
    department: string;
  };
  citations?: Citation[];
  confidence_score?: number;
  trace?: AgentTraceStep[];
}
