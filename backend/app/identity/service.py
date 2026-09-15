import logging
import uuid
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from app.core.canonical import (
    ChannelType,
    PermissionLevel,
    LinkVerificationType,
    ChannelAccountLink,
    IdentityMapping,
    IdentityAuditEvent,
    ManualLinkRequest,
    ManualLinkRequestStatus
)
from app.core.membership import membership_store

logger = logging.getLogger("thread.identity")

MIN_VERIFIED_CONFIDENCE = 0.8

class IdentityResolutionResult(BaseModel):
    """
    Authoritative result of resolving a channel account to an internal canonical identity.
    """
    person_id: str
    organization_id: str
    is_registered_member: bool
    member_id: Optional[str] = None
    permission_level: PermissionLevel
    allowed_scopes: List[PermissionLevel]
    confidence: float
    is_verified: bool
    channel_link: Optional[ChannelAccountLink] = None
    is_synthetic_public: bool = False
    evidence: Dict[str, Any] = Field(default_factory=dict)

class IdentityPersistenceError(RuntimeError):
    """Raised when durable identity persistence fails or is not configured in production."""
    pass

class CrossChannelIdentityService:
    """
    Authoritative Cross-Channel Identity Mapping Service.
    
    Security Guarantees:
    1. IMMUTABLE ACCOUNT IDENTIFIERS:
       Maps immutable platform IDs (Discord snowflake, GitHub user ID, Slack user ID)
       to one internal canonical person. Usernames and display names are mutable metadata only.
    2. STRICT PROHIBITION OF NAME-BASED AUTOMATIC MERGES:
       Never merges accounts based on matching usernames, handles, or display names.
       Name collisions on external channels produce distinct, isolated public identities.
    3. TENANT ENFORCEMENT BEFORE INGESTION:
       All mappings, resolutions, and role lookups require organization_id.
       Cross-tenant account link leakage is strictly rejected.
    4. AUDITABLE EVIDENCE & CONFIDENCE:
       Every account link persists verification type, confidence score, and verifiable evidence payload.
       Only links with is_verified=True and confidence >= 0.8 inherit internal core organization permissions.
    5. REVOCATION AND AUDIT TRAIL:
       Active links can be explicitly revoked, preserving historical audit log in PostgreSQL.
    """
    def __init__(self):
        # Primary lookup: f"{org_id}:{channel_type.value}:{account_id}" -> ChannelAccountLink
        self._account_links: Dict[str, ChannelAccountLink] = {}
        # Reverse lookup: f"{org_id}:{person_id}" -> List[ChannelAccountLink]
        self._person_links: Dict[str, List[ChannelAccountLink]] = {}
        self._audit_logs: List[IdentityAuditEvent] = []
        self._manual_requests: Dict[str, ManualLinkRequest] = {}
        self._init_defaults()

    def _init_defaults(self):
        """Initializes default verified links matching initial seed members."""
        # Arjun: Discord Lead Organizer
        self.link_account(
            organization_id="gdg_mcet",
            person_id="usr_arjun",
            channel_type=ChannelType.DISCORD,
            account_id="discord_arjun_101",
            username="arjun_gdg",
            display_name="Arjun Sharma",
            link_type=LinkVerificationType.ORGANIZER_MANUAL,
            confidence=1.0,
            evidence={"verified_by": "bootstrap", "reason": "Founder Organizer"},
            is_bootstrap=True
        )

        # Arjun: GitHub Lead Developer
        self.link_account(
            organization_id="gdg_mcet",
            person_id="usr_arjun",
            channel_type=ChannelType.GITHUB,
            account_id="583231",  # GitHub numeric user ID
            username="arjun-dev",
            display_name="Arjun Sharma",
            link_type=LinkVerificationType.OAUTH_VERIFIED,
            confidence=1.0,
            evidence={"oauth_provider": "github", "verified_at": "2026-09-01T00:00:00Z"},
            is_bootstrap=True
        )

        # Priya: Tech Lead GitHub & Discord
        self.link_account(
            organization_id="gdg_mcet",
            person_id="usr_priya",
            channel_type=ChannelType.GITHUB,
            account_id="791245",
            username="priya-tech",
            display_name="Priya Ramesh",
            link_type=LinkVerificationType.ORGANIZER_MANUAL,
            confidence=1.0,
            evidence={"verified_by": "usr_arjun"},
            is_bootstrap=True
        )

    def _account_key(self, organization_id: str, channel_type: ChannelType, account_id: str) -> str:
        return f"{organization_id}:{channel_type.value}:{str(account_id).strip()}"

    def link_account(
        self,
        organization_id: str,
        person_id: str,
        channel_type: ChannelType,
        account_id: str,
        link_type: LinkVerificationType,
        confidence: float = 1.0,
        evidence: Optional[Dict[str, Any]] = None,
        username: Optional[str] = None,
        display_name: Optional[str] = None,
        email: Optional[str] = None,
        is_bootstrap: bool = False
    ) -> ChannelAccountLink:
        """
        Links an immutable channel account to a canonical person within an organization.
        Enforces tenant isolation and rejects cross-organization linking.
        """
        if not organization_id or not person_id or not account_id:
            raise ValueError("organization_id, person_id, and account_id must all be non-empty.")

        # Verify person exists in this organization or is a registered member
        member = membership_store.get_identity_context(user_id=person_id, organization_id=organization_id)
        if not member.member_id:
            # If person exists globally but not in this org, prevent cross-org leak
            if membership_store.get_person(person_id):
                raise ValueError(
                    f"Cross-organization linking rejected: user '{person_id}' is not a member of organization '{organization_id}'."
                )

        is_verified = (
            link_type in (LinkVerificationType.OAUTH_VERIFIED, LinkVerificationType.ORGANIZER_MANUAL, LinkVerificationType.EMAIL_VERIFIED)
            and confidence >= MIN_VERIFIED_CONFIDENCE
        )

        key = self._account_key(organization_id, channel_type, account_id)
        existing = self._account_links.get(key)
        if existing and existing.person_id != person_id and existing.is_active:
            raise ValueError(
                f"Account '{account_id}' on channel '{channel_type.value}' is already linked to person '{existing.person_id}' "
                f"in organization '{organization_id}'. Revoke or unlink existing mapping first before reassigning."
            )

        link = ChannelAccountLink(
            organization_id=organization_id,
            person_id=person_id,
            channel_type=channel_type,
            account_id=str(account_id).strip(),
            username=username,
            display_name=display_name,
            email=email,
            link_type=link_type,
            confidence=confidence,
            evidence=evidence or {},
            is_verified=is_verified,
            is_active=True,
            revoked_at=None,
            revoked_by=None
        )

        # 1. Durable database persistence FIRST (fail closed)
        try:
            self._persist_link_to_db(link, is_bootstrap=is_bootstrap)
        except IdentityPersistenceError:
            raise
        except Exception as e:
            raise IdentityPersistenceError(f"Failed to persist identity link to durable database: {e}") from e

        # 2. Only after durable persistence succeeds, update local memory cache
        self._account_links[key] = link
        person_key = f"{organization_id}:{person_id}"
        links = self._person_links.setdefault(person_key, [])
        links = [l for l in links if l.account_id != link.account_id or l.channel_type != channel_type]
        links.append(link)
        self._person_links[person_key] = links

        # Mirror into legacy membership_store identity mappings for compatibility
        try:
            membership_store.register_identity_mapping(
                organization_id=organization_id,
                channel_type=channel_type,
                external_user_id=str(account_id).strip(),
                internal_user_id=person_id,
                external_username=username,
                metadata={"confidence": confidence, "link_type": link_type.value}
            )
        except Exception:
            pass

        return link

    def _persist_link_to_db(self, link: ChannelAccountLink, is_bootstrap: bool = False):
        """
        Persists channel account link to PostgreSQL database.
        Fails closed: raises IdentityPersistenceError if durable write fails.
        In-memory fallback is restricted to explicitly offline development/test mode.
        """
        import os
        import json
        from app.core.config import settings

        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if not db_url:
            # Check if offline mode or bootstrap is allowed
            if not is_bootstrap and settings.APP_ENV != "development" and not os.getenv("THREAD_ALLOW_OFFLINE_IDENTITY"):
                raise IdentityPersistenceError(
                    "Identity persistence failed: durable database is not configured in production. "
                    "Cannot establish persistent channel account links without database storage."
                )
            return

        try:
            import psycopg2
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO channel_account_links (
                            id, organization_id, person_id, channel_type, account_id,
                            username, display_name, email, link_type, confidence,
                            evidence, is_verified, is_active, revoked_at, revoked_by, linked_at
                        ) VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s::jsonb, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (organization_id, channel_type, account_id) DO UPDATE SET
                            person_id = EXCLUDED.person_id,
                            username = EXCLUDED.username,
                            display_name = EXCLUDED.display_name,
                            email = EXCLUDED.email,
                            link_type = EXCLUDED.link_type,
                            confidence = EXCLUDED.confidence,
                            evidence = EXCLUDED.evidence,
                            is_verified = EXCLUDED.is_verified,
                            is_active = EXCLUDED.is_active,
                            revoked_at = EXCLUDED.revoked_at,
                            revoked_by = EXCLUDED.revoked_by,
                            linked_at = EXCLUDED.linked_at;
                    """, (
                        link.id, link.organization_id, link.person_id, link.channel_type.value, link.account_id,
                        link.username, link.display_name, link.email, link.link_type.value, link.confidence,
                        json.dumps(link.evidence), link.is_verified, link.is_active, link.revoked_at, link.revoked_by, link.linked_at
                    ))
                conn.commit()
        except Exception as e:
            logger.error(f"Durable database identity link persistence failure: {e}")
            raise IdentityPersistenceError(f"Failed to persist identity link to durable database: {e}") from e


    def resolve_identity(
        self,
        organization_id: str,
        channel_type: ChannelType,
        account_id: str,
        username: Optional[str] = None,
        display_name: Optional[str] = None,
        email: Optional[str] = None
    ) -> IdentityResolutionResult:
        """
        Resolves an immutable external channel account to a canonical person.
        
        CRITICAL SECURITY RULES:
        1. Lookups are strictly keyed by (organization_id, channel_type, account_id).
        2. Prohibits name-based automatic merges:
           If (account_id) is NOT linked, an incoming username/display_name that matches
           an existing core organizer will NOT be granted internal access!
           A distinct synthetic public identity is generated for that unlinked account.
        3. Enforces organization membership and active status for internal core permissions.
        """
        if not organization_id:
            raise ValueError("organization_id is strictly required for identity resolution.")

        str_account_id = str(account_id).strip()
        key = self._account_key(organization_id, channel_type, str_account_id)
        link = self._account_links.get(key)

        revocation_noted = False
        if not link:
            # Query PostgreSQL database if connected
            import os
            db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
            if db_url:
                try:
                    import psycopg2
                    with psycopg2.connect(db_url) as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                SELECT id, organization_id, person_id, channel_type, account_id,
                                       username, display_name, email, link_type, confidence,
                                       evidence, is_verified, is_active, revoked_at, revoked_by, linked_at
                                FROM channel_account_links
                                WHERE organization_id = %s AND channel_type = %s AND account_id = %s;
                            """, (organization_id, channel_type.value, str_account_id))
                            row = cur.fetchone()
                            if row:
                                link = ChannelAccountLink(
                                    id=row[0],
                                    organization_id=row[1],
                                    person_id=row[2],
                                    channel_type=ChannelType(row[3]),
                                    account_id=row[4],
                                    username=row[5],
                                    display_name=row[6],
                                    email=row[7],
                                    link_type=LinkVerificationType(row[8]),
                                    confidence=row[9],
                                    evidence=row[10] if isinstance(row[10], dict) else {},
                                    is_verified=row[11],
                                    is_active=row[12],
                                    revoked_at=row[13],
                                    revoked_by=row[14],
                                    linked_at=row[15]
                                )
                                self._account_links[key] = link
                except Exception as e:
                    logger.warning(f"Database identity link lookup error: {e}")

        # If link has been revoked or deactivated, strictly disallow internal resolution
        if link and (not link.is_active or link.revoked_at is not None):
            revocation_noted = True
            link = None

        if link:
            # Verified linked account found
            ident_ctx = membership_store.get_identity_context(user_id=link.person_id, organization_id=organization_id)
            
            # If the link is not verified or low confidence, downgrade internal permissions to public
            if not link.is_verified or link.confidence < MIN_VERIFIED_CONFIDENCE:
                return IdentityResolutionResult(
                    person_id=link.person_id,
                    organization_id=organization_id,
                    is_registered_member=ident_ctx.is_active,
                    member_id=ident_ctx.member_id,
                    permission_level=PermissionLevel.PUBLIC_COMMUNITY,
                    allowed_scopes=[PermissionLevel.PUBLIC_COMMUNITY],
                    confidence=link.confidence,
                    is_verified=False,
                    channel_link=link,
                    is_synthetic_public=False,
                    evidence={"warning": "Unverified or low-confidence link; scoped to PUBLIC_COMMUNITY"}
                )

            # Active verified member
            has_internal = (
                ident_ctx.is_active and PermissionLevel.INTERNAL_CORE in ident_ctx.permission_scopes
            )
            perm = PermissionLevel.INTERNAL_CORE if has_internal else PermissionLevel.PUBLIC_COMMUNITY

            return IdentityResolutionResult(
                person_id=link.person_id,
                organization_id=organization_id,
                is_registered_member=ident_ctx.is_active,
                member_id=ident_ctx.member_id,
                permission_level=perm,
                allowed_scopes=ident_ctx.permission_scopes,
                confidence=link.confidence,
                is_verified=link.is_verified,
                channel_link=link,
                is_synthetic_public=False,
                evidence=link.evidence
            )

        # =========================================================================
        # PROHIBIT NAME-BASED AUTOMATIC MERGES:
        # The account_id is not linked. Even if username or display_name matches
        # "arjun", "priya", or any lead organizer, WE MUST NOT MERGE!
        # Create a distinct isolated synthetic identity for this channel account.
        # =========================================================================
        synthetic_person_id = f"ext_{channel_type.value}_{str_account_id}"

        collision_flag = False
        check_names = [n.strip().lower() for n in (username, display_name) if n and n.strip()]
        if check_names:
            for uid, person in membership_store._persons.items():
                p_name = person.name.lower() if person.name else ""
                p_email_user = person.email.split('@')[0].lower() if person.email else ""
                for cn in check_names:
                    if cn == p_name or cn == p_email_user or (p_name and cn in p_name) or (p_email_user and cn in p_email_user):
                        collision_flag = True
                        logger.warning(
                            f"Potential name collision or spoofing attempt: external account '{str_account_id}' "
                            f"uses name/username '{cn}' which matches internal member '{uid}'. "
                            "Rejecting automatic merge; isolating as synthetic public person."
                        )
                        break
                if collision_flag:
                    break

        evidence = {
            "unlinked": True,
            "channel_type": channel_type.value,
            "account_id": str_account_id,
            "username": username,
            "display_name": display_name,
            "potential_name_collision": collision_flag,
            "revoked": revocation_noted,
            "resolution_reason": "Account link has been revoked." if revocation_noted else "No verified account link found. Synthetic public identity generated."
        }

        return IdentityResolutionResult(
            person_id=synthetic_person_id,
            organization_id=organization_id,
            is_registered_member=False,
            member_id=None,
            permission_level=PermissionLevel.PUBLIC_COMMUNITY,
            allowed_scopes=[PermissionLevel.PUBLIC_COMMUNITY],
            confidence=0.0,
            is_verified=False,
            channel_link=None,
            is_synthetic_public=True,
            evidence=evidence
        )

    def get_person_accounts(self, organization_id: str, person_id: str) -> List[ChannelAccountLink]:
        """Returns all linked channel accounts for a person in an organization."""
        person_key = f"{organization_id}:{person_id}"
        return list(self._person_links.get(person_key, []))

    def revoke_account_link(
        self,
        organization_id: str,
        channel_type: ChannelType,
        account_id: str,
        actor_person_id: str,
        reason: Optional[str] = None
    ) -> bool:
        """
        Revokes an active channel account link.
        Sets is_active=False, revoked_at=now, revoked_by=actor_person_id.
        Durable update to PostgreSQL + local memory cache + identity audit log.
        """
        key = self._account_key(organization_id, channel_type, account_id)
        link = self._account_links.get(key)
        now = datetime.now(timezone.utc)

        # Update in DB
        import os
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE channel_account_links
                            SET is_active = FALSE, revoked_at = %s, revoked_by = %s
                            WHERE organization_id = %s AND channel_type = %s AND account_id = %s;
                        """, (now, actor_person_id, organization_id, channel_type.value, str(account_id).strip()))
                    conn.commit()
            except Exception as e:
                logger.error(f"Failed to record link revocation in DB: {e}")
                raise IdentityPersistenceError(f"Failed to record link revocation in database: {e}") from e

        person_id = link.person_id if link else f"ext_{channel_type.value}_{account_id}"

        if link:
            link.is_active = False
            link.revoked_at = now
            link.revoked_by = actor_person_id

            # Remove from active person links list
            person_key = f"{organization_id}:{link.person_id}"
            if person_key in self._person_links:
                self._person_links[person_key] = [
                    l for l in self._person_links[person_key]
                    if not (l.channel_type == channel_type and l.account_id == link.account_id)
                ]

        # Record audit event
        self.record_audit_event(
            organization_id=organization_id,
            person_id=person_id,
            channel_type=channel_type,
            account_id=str(account_id).strip(),
            event_type="link_revoked",
            actor_person_id=actor_person_id,
            evidence={"reason": reason or "Revoked by user or administrator."}
        )
        return True

    def record_audit_event(
        self,
        organization_id: str,
        person_id: str,
        channel_type: ChannelType,
        account_id: str,
        event_type: str,
        actor_person_id: str,
        evidence: Optional[Dict[str, Any]] = None
    ) -> IdentityAuditEvent:
        """
        Records an immutable identity audit event into Supabase PostgreSQL.
        """
        import os
        import json
        event = IdentityAuditEvent(
            organization_id=organization_id,
            person_id=person_id,
            channel_type=channel_type,
            account_id=str(account_id).strip(),
            event_type=event_type,
            actor_person_id=actor_person_id,
            evidence=evidence or {},
            created_at=datetime.now(timezone.utc)
        )
        self._audit_logs.append(event)

        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO identity_audit_log (
                                id, organization_id, person_id, channel_type, account_id,
                                event_type, actor_person_id, evidence, created_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s);
                        """, (
                            event.id, event.organization_id, event.person_id, event.channel_type.value, event.account_id,
                            event.event_type, event.actor_person_id, json.dumps(event.evidence), event.created_at
                        ))
                    conn.commit()
            except Exception as e:
                logger.error(f"Failed to persist identity audit event to database: {e}")
                if os.getenv("THREAD_RUN_LIVE_SUPABASE_TESTS") == "1":
                    raise IdentityPersistenceError(f"Failed to persist identity audit event: {e}") from e

        return event

    def get_audit_events(
        self,
        organization_id: str,
        person_id: Optional[str] = None,
        limit: int = 50
    ) -> List[IdentityAuditEvent]:
        """Queries immutable audit logs for an organization."""
        import os
        import json
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        if person_id:
                            cur.execute("""
                                SELECT id, organization_id, person_id, channel_type, account_id,
                                       event_type, actor_person_id, evidence, created_at
                                FROM identity_audit_log
                                WHERE organization_id = %s AND person_id = %s
                                ORDER BY created_at DESC LIMIT %s;
                            """, (organization_id, person_id, limit))
                        else:
                            cur.execute("""
                                SELECT id, organization_id, person_id, channel_type, account_id,
                                       event_type, actor_person_id, evidence, created_at
                                FROM identity_audit_log
                                WHERE organization_id = %s
                                ORDER BY created_at DESC LIMIT %s;
                            """, (organization_id, limit))
                        rows = cur.fetchall()
                        return [
                            IdentityAuditEvent(
                                id=r[0], organization_id=r[1], person_id=r[2], channel_type=ChannelType(r[3]),
                                account_id=r[4], event_type=r[5], actor_person_id=r[6],
                                evidence=r[7] if isinstance(r[7], dict) else json.loads(r[7] or "{}"),
                                created_at=r[8]
                            )
                            for r in rows
                        ]
            except Exception as e:
                logger.warning(f"Failed to fetch identity audit logs from database: {e}")

        # In-memory fallback
        matching = [
            e for e in reversed(self._audit_logs)
            if e.organization_id == organization_id and (not person_id or e.person_id == person_id)
        ]
        return matching[:limit]

    def create_manual_link_request(
        self,
        organization_id: str,
        person_id: str,
        channel_type: ChannelType,
        account_id: str,
        reason: str,
        username: Optional[str] = None,
        evidence_notes: Optional[str] = None
    ) -> ManualLinkRequest:
        """Creates an organizer-reviewed manual link request."""
        import os
        str_account_id = str(account_id).strip()
        if channel_type == ChannelType.GITHUB and not str_account_id.isdigit():
            raise ValueError(f"GitHub account_id must be an immutable numeric ID, got '{str_account_id}'.")

        if not reason or not reason.strip():
            raise ValueError("A clear justification reason is required for manual account link requests.")

        # Check existing active link
        key = self._account_key(organization_id, channel_type, str_account_id)
        existing = self._account_links.get(key)
        if existing and existing.is_active:
            raise ValueError(f"Account '{str_account_id}' is already actively linked to person '{existing.person_id}'.")

        # Check pending requests
        for r in self._manual_requests.values():
            if (
                r.organization_id == organization_id
                and r.channel_type == channel_type
                and r.account_id == str_account_id
                and r.status == ManualLinkRequestStatus.PENDING
            ):
                raise ValueError(f"A pending manual link request already exists for account '{str_account_id}'.")

        req = ManualLinkRequest(
            organization_id=organization_id,
            person_id=person_id,
            channel_type=channel_type,
            account_id=str_account_id,
            username=username,
            reason=reason.strip(),
            evidence_notes=evidence_notes,
            status=ManualLinkRequestStatus.PENDING,
            requested_at=datetime.now(timezone.utc)
        )
        self._manual_requests[req.id] = req

        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO manual_link_requests (
                                id, organization_id, person_id, channel_type, account_id,
                                username, reason, evidence_notes, status, requested_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                        """, (
                            req.id, req.organization_id, req.person_id, req.channel_type.value, req.account_id,
                            req.username, req.reason, req.evidence_notes, req.status.value, req.requested_at
                        ))
                    conn.commit()
            except Exception as e:
                logger.error(f"Failed to persist manual link request to database: {e}")
                if os.getenv("THREAD_RUN_LIVE_SUPABASE_TESTS") == "1":
                    raise IdentityPersistenceError(f"Failed to persist manual link request: {e}") from e

        self.record_audit_event(
            organization_id=organization_id,
            person_id=person_id,
            channel_type=channel_type,
            account_id=str_account_id,
            event_type="manual_requested",
            actor_person_id=person_id,
            evidence={"request_id": req.id, "reason": reason, "username": username}
        )
        return req

    def get_manual_link_requests(
        self,
        organization_id: str,
        status: Optional[str] = None
    ) -> List[ManualLinkRequest]:
        """Lists manual link requests for an organization."""
        import os
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        if status:
                            cur.execute("""
                                SELECT id, organization_id, person_id, channel_type, account_id,
                                       username, reason, evidence_notes, status, requested_at,
                                       reviewed_by, reviewed_at, review_notes
                                FROM manual_link_requests
                                WHERE organization_id = %s AND status = %s
                                ORDER BY requested_at DESC;
                            """, (organization_id, status))
                        else:
                            cur.execute("""
                                SELECT id, organization_id, person_id, channel_type, account_id,
                                       username, reason, evidence_notes, status, requested_at,
                                       reviewed_by, reviewed_at, review_notes
                                FROM manual_link_requests
                                WHERE organization_id = %s
                                ORDER BY requested_at DESC;
                            """, (organization_id,))
                        rows = cur.fetchall()
                        return [
                            ManualLinkRequest(
                                id=r[0], organization_id=r[1], person_id=r[2], channel_type=ChannelType(r[3]),
                                account_id=r[4], username=r[5], reason=r[6], evidence_notes=r[7],
                                status=ManualLinkRequestStatus(r[8]), requested_at=r[9],
                                reviewed_by=r[10], reviewed_at=r[11], review_notes=r[12]
                            )
                            for r in rows
                        ]
            except Exception as e:
                logger.warning(f"Failed to fetch manual link requests from database: {e}")

        # In-memory fallback
        matching = [
            r for r in self._manual_requests.values()
            if r.organization_id == organization_id and (not status or r.status.value == status)
        ]
        return sorted(matching, key=lambda x: x.requested_at, reverse=True)

    def review_manual_link_request(
        self,
        request_id: str,
        reviewer_person_id: str,
        action: str,
        review_notes: Optional[str] = None
    ) -> ManualLinkRequest:
        """Organizer review of a manual link request (approve or reject)."""
        import os
        req = self._manual_requests.get(request_id)
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")

        if not req and db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT id, organization_id, person_id, channel_type, account_id,
                                   username, reason, evidence_notes, status, requested_at,
                                   reviewed_by, reviewed_at, review_notes
                            FROM manual_link_requests
                            WHERE id = %s;
                        """, (request_id,))
                        row = cur.fetchone()
                        if row:
                            req = ManualLinkRequest(
                                id=row[0], organization_id=row[1], person_id=row[2], channel_type=ChannelType(row[3]),
                                account_id=row[4], username=row[5], reason=row[6], evidence_notes=row[7],
                                status=ManualLinkRequestStatus(row[8]), requested_at=row[9],
                                reviewed_by=row[10], reviewed_at=row[11], review_notes=row[12]
                            )
                            self._manual_requests[req.id] = req
            except Exception as e:
                logger.warning(f"Database lookup for manual link request {request_id} failed: {e}")

        if not req:
            raise ValueError(f"Manual link request '{request_id}' not found.")

        if req.status != ManualLinkRequestStatus.PENDING:
            raise ValueError(f"Manual link request '{request_id}' has already been reviewed (status: {req.status.value}).")

        now = datetime.now(timezone.utc)
        action_lower = action.strip().lower()

        if action_lower == "approve":
            req.status = ManualLinkRequestStatus.APPROVED
            req.reviewed_by = reviewer_person_id
            req.reviewed_at = now
            req.review_notes = review_notes

            # Perform the verified link
            self.link_account(
                organization_id=req.organization_id,
                person_id=req.person_id,
                channel_type=req.channel_type,
                account_id=req.account_id,
                username=req.username,
                link_type=LinkVerificationType.ORGANIZER_MANUAL,
                confidence=1.0,
                evidence={
                    "approved_by": reviewer_person_id,
                    "request_id": req.id,
                    "review_notes": review_notes or "",
                    "original_reason": req.reason
                }
            )

            event_type = "manual_approved"

        elif action_lower == "reject":
            req.status = ManualLinkRequestStatus.REJECTED
            req.reviewed_by = reviewer_person_id
            req.reviewed_at = now
            req.review_notes = review_notes
            event_type = "manual_rejected"
        else:
            raise ValueError(f"Invalid review action '{action}'. Must be 'approve' or 'reject'.")

        # Update in DB
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE manual_link_requests
                            SET status = %s, reviewed_by = %s, reviewed_at = %s, review_notes = %s
                            WHERE id = %s;
                        """, (req.status.value, req.reviewed_by, req.reviewed_at, req.review_notes, req.id))
                    conn.commit()
            except Exception as e:
                logger.error(f"Failed to update manual link request status in DB: {e}")
                if os.getenv("THREAD_RUN_LIVE_SUPABASE_TESTS") == "1":
                    raise IdentityPersistenceError(f"Failed to update manual link request: {e}") from e

        self.record_audit_event(
            organization_id=req.organization_id,
            person_id=req.person_id,
            channel_type=req.channel_type,
            account_id=req.account_id,
            event_type=event_type,
            actor_person_id=reviewer_person_id,
            evidence={"request_id": req.id, "action": action_lower, "review_notes": review_notes}
        )

        return req

    def unlink_account(self, organization_id: str, channel_type: ChannelType, account_id: str) -> bool:
        """Removes a channel account link."""
        key = self._account_key(organization_id, channel_type, account_id)
        link = self._account_links.pop(key, None)
        if not link:
            return False

        person_key = f"{organization_id}:{link.person_id}"
        if person_key in self._person_links:
            self._person_links[person_key] = [
                l for l in self._person_links[person_key]
                if not (l.channel_type == channel_type and l.account_id == link.account_id)
            ]
        return True

    def clear(self):
        self._account_links.clear()
        self._person_links.clear()
        self._audit_logs.clear()
        self._manual_requests.clear()

    def reset(self):
        self.clear()
        self._init_defaults()

identity_service = CrossChannelIdentityService()

