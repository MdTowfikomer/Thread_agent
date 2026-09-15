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
    IdentityMapping
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
    """
    def __init__(self):
        # Primary lookup: f"{org_id}:{channel_type.value}:{account_id}" -> ChannelAccountLink
        self._account_links: Dict[str, ChannelAccountLink] = {}
        # Reverse lookup: f"{org_id}:{person_id}" -> List[ChannelAccountLink]
        self._person_links: Dict[str, List[ChannelAccountLink]] = {}
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
            evidence={"verified_by": "bootstrap", "reason": "Founder Organizer"}
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
            evidence={"oauth_provider": "github", "verified_at": "2026-09-01T00:00:00Z"}
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
            evidence={"verified_by": "usr_arjun"}
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
        evidence: Optional[Dict[str, Any]] = None,
        confidence: float = 1.0,
        username: Optional[str] = None,
        display_name: Optional[str] = None,
        email: Optional[str] = None
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
        if existing and existing.person_id != person_id:
            raise ValueError(
                f"Account '{account_id}' on channel '{channel_type.value}' is already linked to person '{existing.person_id}' "
                f"in organization '{organization_id}'. Unlink existing mapping first before reassigning."
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
            is_verified=is_verified
        )

        self._account_links[key] = link
        person_key = f"{organization_id}:{person_id}"
        links = self._person_links.setdefault(person_key, [])
        links = [l for l in links if l.account_id != link.account_id or l.channel_type != channel_type]
        links.append(link)
        self._person_links[person_key] = links

        # Mirror to PostgreSQL if database connection is configured
        self._persist_link_to_db(link)

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

    def _persist_link_to_db(self, link: ChannelAccountLink):
        """Persists channel account link to PostgreSQL database if connected."""
        import os
        import json
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if not db_url:
            return
        try:
            import psycopg2
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO channel_account_links (
                            id, organization_id, person_id, channel_type, account_id,
                            username, display_name, email, link_type, confidence,
                            evidence, is_verified, linked_at
                        ) VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s::jsonb, %s, %s
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
                            linked_at = EXCLUDED.linked_at;
                    """, (
                        link.id, link.organization_id, link.person_id, link.channel_type.value, link.account_id,
                        link.username, link.display_name, link.email, link.link_type.value, link.confidence,
                        json.dumps(link.evidence), link.is_verified, link.linked_at
                    ))
                conn.commit()
        except Exception as e:
            logger.warning(f"Database identity link persistence error: {e}")

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
                                       evidence, is_verified, linked_at
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
                                    linked_at=row[12]
                                )
                                self._account_links[key] = link
                except Exception as e:
                    logger.warning(f"Database identity link lookup error: {e}")

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
            "resolution_reason": "No verified account link found. Synthetic public identity generated."
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

    def reset(self):
        self.clear()
        self._init_defaults()

identity_service = CrossChannelIdentityService()
