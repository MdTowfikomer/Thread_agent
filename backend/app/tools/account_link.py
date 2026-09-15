import os
import secrets
import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Tuple, Dict, Any, Optional

from app.core.config import settings
from app.core.canonical import ChannelType, LinkVerificationType
from app.identity.service import identity_service

logger = logging.getLogger("thread.tools.account_link")

MAX_FAILED_ATTEMPTS = 5
RATE_LIMIT_WINDOW_SECONDS = 900  # 15 minutes


class AccountLinkTool:
    """
    Cryptographically secure cross-platform account linking tool (!link).
    
    SECURITY CONTRACT:
    1. Cryptographic Entropy: Generates 256-bit secure random tokens (base64url).
    2. Zero Plaintext Token Storage: Only cryptographic SHA-256 digests are stored in the database.
    3. Fail-Closed Persistence: Strictly requires database connectivity; zero in-memory fallback.
    4. Atomic Consumption: Single-statement PostgreSQL atomic UPDATE ... WHERE used=false RETURNING.
       Prevents double-redemption race conditions across concurrent worker threads.
    5. Brute-Force Rate Limiting: Blocks callers exceeding 5 failed redemption attempts per 15 minutes.
    """
    def __init__(self):
        # (platform, account_id) -> list of timestamp failures
        self._failed_attempts: Dict[str, list] = defaultdict(list)

    def _get_db_conn(self):
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if not db_url:
            return None
        try:
            import psycopg2
            return psycopg2.connect(db_url)
        except Exception as e:
            logger.error(f"AccountLink database connection failed: {e}")
            return None

    @staticmethod
    def _hash_token(raw_token: str) -> str:
        """Compute deterministic SHA-256 digest of token."""
        return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()

    def _check_rate_limit(self, target_platform: str, target_account_id: str) -> bool:
        """Check if caller is currently rate limited due to excessive failed attempts."""
        key = f"{target_platform.lower()}:{str(target_account_id)}"
        now = datetime.now(timezone.utc)
        recent = [
            ts for ts in self._failed_attempts[key]
            if (now - ts).total_seconds() < RATE_LIMIT_WINDOW_SECONDS
        ]
        self._failed_attempts[key] = recent
        return len(recent) >= MAX_FAILED_ATTEMPTS

    def _record_failed_attempt(self, target_platform: str, target_account_id: str) -> None:
        """Record a failed redemption attempt for rate limiting."""
        key = f"{target_platform.lower()}:{str(target_account_id)}"
        self._failed_attempts[key].append(datetime.now(timezone.utc))

    def generate_link_token(
        self,
        initiating_platform: str,
        initiating_account_id: str,
        initiating_username: str,
        person_id: str,
        org_id: str = "gdg_mcet",
        expires_minutes: int = 30
    ) -> str:
        """
        Generate a 256-bit secure token, persist only its SHA-256 hash to PostgreSQL,
        and return the raw token to the user. Fails closed if database is unreachable.
        """
        conn = self._get_db_conn()
        if not conn:
            raise RuntimeError("Identity link service is currently unavailable. Database connection required.")

        # 256 bits of cryptographic entropy via secrets.token_urlsafe(32)
        raw_token = f"LINK_{secrets.token_urlsafe(32)}"
        token_hash = self._hash_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO account_link_tokens (
                            token_hash, person_id, organization_id,
                            initiating_platform, initiating_account_id, initiating_username,
                            expires_at, used, attempts, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, 0, NOW());
                    """, (
                        token_hash,
                        person_id,
                        org_id,
                        initiating_platform.lower(),
                        str(initiating_account_id),
                        initiating_username,
                        expires_at
                    ))
            return raw_token
        except Exception as e:
            logger.error(f"Failed to persist account link token hash: {e}")
            raise RuntimeError(f"Unable to generate account link token: {e}") from e
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def redeem_link_token(
        self,
        raw_token: str,
        target_platform: str,
        target_account_id: str,
        target_username: str,
        target_display_name: str = "",
        org_id: str = "gdg_mcet"
    ) -> Tuple[bool, str]:
        """
        Atomically redeem a token and link target account to the originating person.
        Enforces atomic single-use consumption and brute-force rate limits.
        """
        targ_plat = target_platform.lower()
        targ_acc = str(target_account_id)

        # 1. Check rate limit
        if self._check_rate_limit(targ_plat, targ_acc):
            return False, "⛔ Too many failed redemption attempts. Please wait 15 minutes before trying again."

        conn = self._get_db_conn()
        if not conn:
            return False, "❌ Identity link service is currently unavailable. Please try again shortly."

        token_hash = self._hash_token(raw_token)

        try:
            with conn:
                with conn.cursor() as cur:
                    # 2. Atomic single-statement claim
                    cur.execute("""
                        UPDATE account_link_tokens
                        SET used = TRUE,
                            used_at = NOW(),
                            redeemed_by_platform = %s,
                            redeemed_by_account_id = %s
                        WHERE token_hash = %s
                          AND used = FALSE
                          AND expires_at > NOW()
                        RETURNING person_id, organization_id, initiating_platform, initiating_account_id, initiating_username;
                    """, (targ_plat, targ_acc, token_hash))

                    row = cur.fetchone()
                    if not row:
                        # Failed claim: increment attempt counter and record failure
                        cur.execute("UPDATE account_link_tokens SET attempts = attempts + 1 WHERE token_hash = %s;", (token_hash,))
                        self._record_failed_attempt(targ_plat, targ_acc)
                        return False, "❌ Invalid, expired, or already redeemed link token. Please generate a fresh token with `!link`."

                    person_id, db_org_id, init_plat, init_acc, init_user = row[0], row[1], row[2], row[3], row[4]

                    # 3. Reject same-platform linking
                    if init_plat == targ_plat:
                        # Revert atomic claim since it was invalid input
                        cur.execute("UPDATE account_link_tokens SET used = FALSE, used_at = NULL WHERE token_hash = %s;", (token_hash,))
                        return False, f"⚠️ This link token was generated on {init_plat.capitalize()}. Please redeem it on a different platform (Discord, Slack, or Telegram)."

                    # 4. Map channel type enum
                    try:
                        ch_type = ChannelType(targ_plat)
                    except ValueError:
                        return False, f"Unsupported channel platform: {target_platform}"

                    # 5. Authoritatively link channel account in identity service
                    identity_service.link_account(
                        organization_id=db_org_id,
                        person_id=person_id,
                        channel_type=ch_type,
                        account_id=targ_acc,
                        link_type=LinkVerificationType.CLAIMED_UNVERIFIED,
                        confidence=0.85,
                        username=target_username,
                        display_name=target_display_name or target_username,
                        evidence={"linked_via_token_hash": token_hash[:16], "source_platform": init_plat}
                    )

                    return True, (
                        f"🎉 **Account Successfully Linked!**\n\n"
                        f"Your **{target_platform.capitalize()}** account (`@{target_username}`) is now connected to your "
                        f"community profile (originating from **{init_plat.capitalize()}** as `@{init_user}`).\n"
                        f"Your conversation memory, access permissions, and roles are now synchronized across platforms!"
                    )
        except Exception as e:
            logger.error(f"Redemption error for token hash {token_hash[:12]}: {e}")
            self._record_failed_attempt(targ_plat, targ_acc)
            return False, f"❌ Failed to link account: {e}"
        finally:
            try:
                conn.close()
            except Exception:
                pass


account_link_tool = AccountLinkTool()
