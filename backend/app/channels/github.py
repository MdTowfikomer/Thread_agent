import hmac
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple, Union
from pydantic import BaseModel, Field

from app.core.canonical import (
    ChannelType,
    SourceType,
    PermissionLevel,
    SourceRecord,
    MemoryChunk,
    IngestionReceipt,
    IngestionTrustMode
)
from app.identity.service import identity_service, CrossChannelIdentityService, MIN_VERIFIED_CONFIDENCE
from app.memory.store import memory_store, MemoryStore

logger = logging.getLogger("thread.channels.github")

def parse_iso_datetime(val: Any) -> datetime:
    """
    Strict ISO-8601 parser for GitHub timestamps.
    Fails deterministically on missing or malformed timestamps rather than inventing current time.
    """
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str) and val.strip():
        cleaned = val.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(cleaned)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception as e:
            raise ValueError(f"Malformed GitHub timestamp '{val}': must be valid ISO-8601.") from e
    raise ValueError(f"Missing or invalid timestamp '{val}': authoritative event timestamp is required.")

def verify_github_signature(payload_bytes: bytes, signature_header: Optional[str], secret: str) -> bool:
    """
    Verifies GitHub webhook HMAC-SHA256 signature (X-Hub-Signature-256).
    """
    if not signature_header or not secret:
        return False
    
    parts = signature_header.split("=", 1)
    if len(parts) != 2 or parts[0] != "sha256":
        return False
    
    expected_mac = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_mac, parts[1])

class GitHubEvent(BaseModel):
    """
    Normalized internal model for GitHub events (PRs, reviews, comments, issues, commits).
    """
    event_type: str  # 'pull_request', 'pull_request_review', 'issue_comment', 'issues', 'push'
    action: Optional[str] = None
    organization_id: str
    repository_id: str
    repository_name: str
    is_private: bool = False
    
    # Author identity (immutable ID + mutable handles)
    author_id: str
    author_username: str
    author_name: Optional[str] = None
    author_email: Optional[str] = None
    
    # Content & references
    title: str
    body: str
    source_uri: str
    timestamp: datetime
    
    # Context-specific metadata
    item_number: Optional[int] = None
    commit_sha: Optional[str] = None
    diff_summary: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class GitHubConnector:
    """
    Authoritative GitHub Channel Connector.
    
    Ingests PRs, reviews, comments, issues, and commits into the canonical
    SourceRecord -> MemoryChunk pipeline with:
    1. Author identity resolution through CrossChannelIdentityService.
    2. Strict prohibition of name-based automatic merges.
    3. Authoritative source timestamp & cryptographic provenance hashing.
    4. Organization boundary and repository visibility enforcement.
    """
    channel_type = ChannelType.GITHUB

    def __init__(
        self,
        identities: Optional[CrossChannelIdentityService] = None,
        store: Optional[MemoryStore] = None,
        webhook_secret: Optional[str] = None
    ):
        self.identity_service = identities or identity_service
        self.memory_store = store or memory_store
        self.webhook_secret = webhook_secret

    def parse_webhook_payload(self, event_header: str, payload: Dict[str, Any], organization_id: str) -> List[GitHubEvent]:
        """
        Parses raw GitHub webhook payload into normalized GitHubEvent instances.
        """
        if not organization_id:
            raise ValueError("organization_id is strictly required.")

        repo = payload.get("repository", {})
        repo_id = str(repo.get("id", ""))
        repo_name = repo.get("full_name") or repo.get("name", "unknown_repo")
        is_private = repo.get("private", False)

        events: List[GitHubEvent] = []

        # 1. Pull Request
        if event_header == "pull_request":
            pr = payload.get("pull_request", {})
            user = pr.get("user", {})
            ts = parse_iso_datetime(pr.get("updated_at") or pr.get("created_at"))
            events.append(GitHubEvent(
                event_type="pull_request",
                action=payload.get("action"),
                organization_id=organization_id,
                repository_id=repo_id,
                repository_name=repo_name,
                is_private=is_private,
                author_id=str(user.get("id", "")),
                author_username=user.get("login", "unknown"),
                title=f"PR #{pr.get('number')}: {pr.get('title', '')}",
                body=pr.get("body") or "",
                source_uri=pr.get("html_url", f"https://github.com/{repo_name}/pull/{pr.get('number')}"),
                timestamp=ts,
                item_number=pr.get("number"),
                diff_summary=f"+{pr.get('additions', 0)} -{pr.get('deletions', 0)} ({pr.get('changed_files', 0)} files)",
                metadata={
                    "base_branch": pr.get("base", {}).get("ref"),
                    "head_branch": pr.get("head", {}).get("ref"),
                    "merged": pr.get("merged", False),
                    "state": pr.get("state")
                }
            ))

        # 2. PR Review
        elif event_header == "pull_request_review":
            review = payload.get("review", {})
            pr = payload.get("pull_request", {})
            user = review.get("user", {})
            ts = parse_iso_datetime(review.get("submitted_at") or payload.get("review", {}).get("created_at", datetime.now(timezone.utc)))
            events.append(GitHubEvent(
                event_type="pull_request_review",
                action=payload.get("action"),
                organization_id=organization_id,
                repository_id=repo_id,
                repository_name=repo_name,
                is_private=is_private,
                author_id=str(user.get("id", "")),
                author_username=user.get("login", "unknown"),
                title=f"Review on PR #{pr.get('number')} ({review.get('state', 'COMMENTED')}): {pr.get('title', '')}",
                body=review.get("body") or f"Review state: {review.get('state')}",
                source_uri=review.get("html_url", f"https://github.com/{repo_name}/pull/{pr.get('number')}#review"),
                timestamp=ts,
                item_number=pr.get("number"),
                metadata={"review_state": review.get("state"), "commit_id": review.get("commit_id")}
            ))

        # 3. Issue / PR Comment
        elif event_header in ("issue_comment", "pull_request_review_comment"):
            comment = payload.get("comment", {})
            issue = payload.get("issue") or payload.get("pull_request", {})
            user = comment.get("user", {})
            ts = parse_iso_datetime(comment.get("created_at"))
            is_pr = "pull_request" in payload or "pull_request" in issue
            target_type = "PR" if is_pr else "Issue"
            num = issue.get("number") or payload.get("pull_request", {}).get("number")
            events.append(GitHubEvent(
                event_type=event_header,
                action=payload.get("action"),
                organization_id=organization_id,
                repository_id=repo_id,
                repository_name=repo_name,
                is_private=is_private,
                author_id=str(user.get("id", "")),
                author_username=user.get("login", "unknown"),
                title=f"Comment on {target_type} #{num}: {issue.get('title', '')}",
                body=comment.get("body") or "",
                source_uri=comment.get("html_url", ""),
                timestamp=ts,
                item_number=num,
                metadata={"path": comment.get("path"), "line": comment.get("line")}
            ))

        # 4. Issue
        elif event_header == "issues":
            issue = payload.get("issue", {})
            user = issue.get("user", {})
            ts = parse_iso_datetime(issue.get("updated_at") or issue.get("created_at"))
            events.append(GitHubEvent(
                event_type="issues",
                action=payload.get("action"),
                organization_id=organization_id,
                repository_id=repo_id,
                repository_name=repo_name,
                is_private=is_private,
                author_id=str(user.get("id", "")),
                author_username=user.get("login", "unknown"),
                title=f"Issue #{issue.get('number')}: {issue.get('title', '')}",
                body=issue.get("body") or "",
                source_uri=issue.get("html_url", f"https://github.com/{repo_name}/issues/{issue.get('number')}"),
                timestamp=ts,
                item_number=issue.get("number"),
                metadata={"state": issue.get("state"), "labels": [l.get("name") for l in issue.get("labels", [])]}
            ))

        # 5. Push (Commits)
        elif event_header == "push":
            ref = payload.get("ref", "")
            commits = payload.get("commits", [])
            for c in commits:
                author = c.get("author", {})
                committer = c.get("committer", {})
                ts = parse_iso_datetime(c.get("timestamp"))
                author_email = author.get("email") or committer.get("email")
                author_name = author.get("name") or committer.get("name")
                author_username = author.get("username") or committer.get("username") or "git-commit"
                # If numeric GitHub ID is missing from commit payload, use email or git author key
                author_id = c.get("author", {}).get("id") or author_username
                
                events.append(GitHubEvent(
                    event_type="push",
                    action="commit",
                    organization_id=organization_id,
                    repository_id=repo_id,
                    repository_name=repo_name,
                    is_private=is_private,
                    author_id=str(author_id),
                    author_username=author_username,
                    author_name=author_name,
                    author_email=author_email,
                    title=f"Commit in {repo_name}: {c.get('message', '').splitlines()[0]}",
                    body=c.get("message", ""),
                    source_uri=c.get("url", f"https://github.com/{repo_name}/commit/{c.get('id')}"),
                    timestamp=ts,
                    commit_sha=c.get("id"),
                    metadata={
                        "ref": ref,
                        "added": c.get("added", []),
                        "removed": c.get("removed", []),
                        "modified": c.get("modified", [])
                    }
                ))

        return events

    def ingest_event(
        self,
        event: GitHubEvent,
        trust_mode: IngestionTrustMode = IngestionTrustMode.VERIFIED_CONNECTOR
    ) -> Tuple[SourceRecord, List[MemoryChunk], IngestionReceipt]:
        """
        Ingests a single normalized GitHubEvent into the SourceRecord -> MemoryChunk pipeline.
        Resolves author identity and enforces ACL/provenance rules.
        """
        # 1. Resolve author identity through CrossChannelIdentityService
        # Prohibits name-based automatic merges: only verified links with confidence >= 0.8
        # inherit internal organization permissions.
        ident = self.identity_service.resolve_identity(
            organization_id=event.organization_id,
            channel_type=ChannelType.GITHUB,
            account_id=event.author_id,
            username=event.author_username,
            display_name=event.author_name,
            email=event.author_email
        )

        # 2. Derive Permission Level
        if event.is_private:
            # Private repo requires verified internal membership
            if ident.is_registered_member and ident.is_verified and ident.permission_level == PermissionLevel.INTERNAL_CORE:
                permission = PermissionLevel.INTERNAL_CORE
            else:
                permission = PermissionLevel.PENDING_REVIEW
        else:
            # Public repo: default chunks are PUBLIC_COMMUNITY
            if ident.is_registered_member and ident.is_verified and ident.permission_level == PermissionLevel.INTERNAL_CORE:
                # Core organizers working in public repos can have public or internal chunks;
                # for standard PRs and issues in public repos, defaults to PUBLIC_COMMUNITY
                permission = PermissionLevel.PUBLIC_COMMUNITY
            else:
                permission = PermissionLevel.PUBLIC_COMMUNITY

        # 3. Deterministic Source Hash
        hash_payload = (
            f"github:{event.organization_id}:{event.repository_name}:{event.event_type}:"
            f"{event.item_number or event.commit_sha}:{event.timestamp.isoformat()}:{event.title}:{event.body}"
        )
        source_hash = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()

        # 4. Create SourceRecord
        record_id = f"src_gh_{source_hash[:16]}"
        raw_content = f"{event.title}\n\n{event.body}".strip()
        record = SourceRecord(
            id=record_id,
            organization_id=event.organization_id,
            source_type=SourceType.GITHUB,
            source_uri=event.source_uri,
            external_id=str(event.item_number or event.commit_sha or event.source_uri),
            author_id=ident.person_id,
            author_name=event.author_name or event.author_username or ident.person_id,
            author_role="organizer" if ident.permission_level == PermissionLevel.INTERNAL_CORE else "contributor",
            timestamp=event.timestamp,
            raw_content=raw_content,
            permission=permission,
            hash=source_hash,
            metadata={
                "event_type": event.event_type,
                "action": event.action,
                "repository": event.repository_name,
                "is_private": event.is_private,
                "author_username": event.author_username,
                "author_id": event.author_id,
                "author_email": event.author_email,
                "trust_mode": trust_mode.value,
                "details": event.metadata
            }
        )

        # 5. Build Chunk Content & Metadata
        chunk_id = f"chk_gh_{source_hash[:16]}"
        tags = ["github", event.repository_name, event.event_type]
        if event.action:
            tags.append(event.action)
        if event.item_number:
            tags.append(f"#{event.item_number}")

        content_lines = [
            f"Repository: {event.repository_name}",
            f"Event: {event.event_type.replace('_', ' ').title()}",
            f"Author: {event.author_username} ({ident.person_id})",
            f"Title: {event.title}"
        ]
        if event.diff_summary:
            content_lines.append(f"Diff Summary: {event.diff_summary}")
        if event.body:
            content_lines.append(f"\n{event.body}")

        full_content = "\n".join(content_lines)

        provenance = {
            "channel_type": ChannelType.GITHUB.value,
            "repository": event.repository_name,
            "source_uri": event.source_uri,
            "source_hash": source_hash,
            "source_timestamp": event.timestamp.isoformat(),
            "identity_resolution": {
                "person_id": ident.person_id,
                "is_verified": ident.is_verified,
                "confidence": ident.confidence,
                "is_synthetic_public": ident.is_synthetic_public,
                "evidence": ident.evidence
            },
            "ingestion_version": "1.0",
            "policy_version": "2026.09"
        }

        chunk = MemoryChunk(
            id=chunk_id,
            source_record_id=record_id,
            organization_id=event.organization_id,
            source_type=SourceType.GITHUB,
            source_uri=event.source_uri,
            source_timestamp=event.timestamp,
            source_hash=source_hash,
            author=ident.person_id,
            author_role=record.author_role,
            title=event.title,
            content=full_content,
            permission=permission,
            tags=tags,
            entities={"repository": event.repository_name, "event_type": event.event_type},
            provenance=provenance,
            embedding_status="ready"
        )

        receipt = IngestionReceipt(
            organization_id=event.organization_id,
            source_type=SourceType.GITHUB,
            source_uri=event.source_uri,
            records_ingested=1,
            chunks_created=1,
            status="quarantined" if permission == PermissionLevel.PENDING_REVIEW else "success",
            provenance_summary={
                "event_type": event.event_type,
                "repository": event.repository_name,
                "author": ident.person_id,
                "trust_mode": trust_mode.value
            }
        )

        return record, [chunk], receipt

github_connector = GitHubConnector()
