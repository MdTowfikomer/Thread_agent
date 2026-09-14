from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import uuid

class PermissionLevel(str, Enum):
    PUBLIC_COMMUNITY = "PUBLIC_COMMUNITY"
    INTERNAL_CORE = "INTERNAL_CORE"
    PENDING_REVIEW = "PENDING_REVIEW"

class SourceType(str, Enum):
    SLACK = "slack"
    DISCORD = "discord"
    GITHUB = "github"
    GDRIVE = "gdrive"
    NOTION = "notion"
    PDF = "pdf"
    JIRA = "jira"
    MANUAL = "manual"

class ChannelType(str, Enum):
    DISCORD = "discord"
    SLACK = "slack"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"

# Identity Mapping for Channel Users
class IdentityMapping(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str
    channel_type: ChannelType
    external_user_id: str
    external_username: Optional[str] = None
    internal_user_id: str
    internal_member_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)

class IngestionTrustMode(str, Enum):
    VERIFIED_CONNECTOR = "verified_connector"
    UNVERIFIED_FILE_IMPORT = "unverified_file_import"

# Immutable Audit Record for Import Approval & Promotion
class ImportApprovalRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str
    import_hash: str
    approved_by_user_id: str
    approved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    promoted_chunk_ids: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

# Normalized Channel Message
class ChannelMessage(BaseModel):
    message_id: str
    channel_type: ChannelType
    organization_id: str
    guild_id: Optional[str] = None
    guild_name: Optional[str] = None
    channel_id: str
    channel_name: Optional[str] = None
    author_external_id: str
    author_name: str
    content: str
    timestamp: datetime = Field(..., description="Authoritative external message timestamp. Strictly required.")
    source_uri: Optional[str] = None
    thread_id: Optional[str] = None
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    reactions: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

# Server-Managed Channel Policy / Binding
class ChannelPolicy(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str
    channel_type: ChannelType
    guild_id: Optional[str] = None
    channel_id: str
    channel_name: Optional[str] = None
    permission_scope: PermissionLevel = PermissionLevel.PUBLIC_COMMUNITY
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def permission(self) -> PermissionLevel:
        return self.permission_scope

ChannelBinding = ChannelPolicy

# 1. Person
class Person(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# 2. OrganizationMember
class OrganizationMember(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str
    person_id: str
    is_active: bool = True
    joined_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)

# 3. RoleAssignment
class RoleAssignment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str
    member_id: str
    role_id: str
    role_name: str
    permission: PermissionLevel = PermissionLevel.PUBLIC_COMMUNITY
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# 4. SourceRecord
class SourceRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str
    source_type: SourceType
    source_uri: Optional[str] = None
    external_id: Optional[str] = None
    author_id: Optional[str] = None
    author_name: str
    author_role: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_content: str
    permission: PermissionLevel = PermissionLevel.INTERNAL_CORE
    metadata: Dict[str, Any] = Field(default_factory=dict)
    hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# 5. MemoryChunk
class MemoryChunk(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_record_id: str
    organization_id: str
    source_type: SourceType
    source_uri: Optional[str] = None
    author: str
    author_role: Optional[str] = None
    title: Optional[str] = None
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    permission: PermissionLevel = PermissionLevel.INTERNAL_CORE
    tags: List[str] = Field(default_factory=list)
    entities: Dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[List[float]] = None
    embedding_status: str = Field(default="ready", description="Embedding state: ready or pending_reembed")
    provenance: Dict[str, Any] = Field(default_factory=dict, description="Detailed ingestion provenance trail")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# 6. IngestionReceipt
class IngestionReceipt(BaseModel):
    receipt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str
    source_type: SourceType
    source_uri: Optional[str] = None
    records_ingested: int
    chunks_created: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "success"
    provenance_summary: Dict[str, Any] = Field(default_factory=dict)

# Citations
class Citation(BaseModel):
    item_id: str
    source: SourceType
    author: str
    title: Optional[str] = None
    snippet: str
    permission: PermissionLevel
    source_uri: Optional[str] = None
    relevance_score: float = 0.0

# Access Context for ACL evaluation
class AccessContext(BaseModel):
    user_id: str
    organization_id: str
    role_id: str
    user_permission: PermissionLevel
    allowed_scopes: List[PermissionLevel]

# 9. IdentityContext
class IdentityContext(BaseModel):
    user_id: str
    organization_id: str
    member_id: Optional[str] = None
    is_active: bool = False
    assigned_roles: List[RoleAssignment] = Field(default_factory=list)
    permission_scopes: List[PermissionLevel] = Field(default_factory=list)

# 7. RetrievalReceipt
class RetrievalReceipt(BaseModel):
    receipt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    query: str
    organization_id: str
    allowed_scopes: List[PermissionLevel]
    candidates_before_acl: int
    candidates_after_acl: int
    selected_item_ids: List[str]
    scores: Dict[str, float]
    source_types: List[SourceType]
    retrieval_strategy: str = "deterministic_hybrid_cosine_lexical_pre_acl"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# 8. EvidencePack
class EvidencePack(BaseModel):
    query: str
    organization_id: str
    citations: List[Citation]
    receipt: RetrievalReceipt
    sufficient_evidence: bool = True
    confidence_score: float = 0.0

# Organization and Role Agent configuration
class RoleAgentConfig(BaseModel):
    id: str
    name: str
    role: str
    department: str
    style: str
    avatar: str
    expertise: List[str]

class OrganizationWorkspace(BaseModel):
    id: str
    name: str
    description: str
    default_role_id: str
    roles: List[RoleAgentConfig]
