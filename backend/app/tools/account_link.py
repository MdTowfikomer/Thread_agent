import os
import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import Tuple, Dict, Any, Optional

from app.core.config import settings
from app.core.canonical import ChannelType, LinkVerificationType
from app.identity.service import identity_service

logger = logging.getLogger("thread.tools.account_link")

class AccountLinkTool:
    """
    Cross-platform account link tool (!link).
    Allows community members to merge their identities across Slack, Discord, and Telegram.
    1. User runs `!link` on Platform A -> receives a temporary token.
    2. User runs `!link <TOKEN>` on Platform B -> their Platform B account is mapped to the same Person.
    """
    def __init__(self):
        self._tokens: Dict[str, Dict[str, Any]] = {}

    def _get_db_conn(self):
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if not db_url:
            return None
        try:
            import psycopg2
            return psycopg2.connect(db_url)
        except Exception as e:
            logger.warning(f"Failed to connect to database for account link: {e}")
            return None

    def generate_link_token(
        self,
        initiating_platform: str,
        initiating_account_id: str,
        initiating_username: str,
        person_id: str,
        org_id: str = "gdg_mcet",
        expires_minutes: int = 30
    ) -> str:
        """Generate and store a temporary link token."""
        token = f"LINK-{secrets.token_hex(3).upper()}"
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)

        token_data = {
            "token": token,
            "initiating_platform": initiating_platform.lower(),
            "initiating_account_id": initiating_account_id,
            "initiating_username": initiating_username,
            "person_id": person_id,
            "organization_id": org_id,
            "expires_at": expires_at,
            "used": False
        }
        self._tokens[token] = token_data

        conn = self._get_db_conn()
        if conn:
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO account_link_tokens (
                                token, initiating_platform, initiating_account_id, initiating_username,
                                person_id, organization_id, expires_at, used
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                        """, (
                            token,
                            initiating_platform.lower(),
                            initiating_account_id,
                            initiating_username,
                            person_id,
                            org_id,
                            expires_at,
                            False
                        ))
            except Exception as e:
                logger.warning(f"Failed to persist account link token: {e}")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        return token

    def redeem_link_token(
        self,
        token: str,
        target_platform: str,
        target_account_id: str,
        target_username: str,
        target_display_name: str = "",
        org_id: str = "gdg_mcet"
    ) -> Tuple[bool, str]:
        """
        Redeem a token and link the target account to the originating person.
        """
        clean_token = token.strip().upper()
        token_info = self._tokens.get(clean_token)

        conn = self._get_db_conn()
        if conn and not token_info:
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT token, initiating_platform, initiating_account_id, initiating_username,
                                   person_id, organization_id, expires_at, used
                            FROM account_link_tokens
                            WHERE token = %s;
                        """, (clean_token,))
                        row = cur.fetchone()
                        if row:
                            token_info = {
                                "token": row[0],
                                "initiating_platform": row[1],
                                "initiating_account_id": row[2],
                                "initiating_username": row[3],
                                "person_id": row[4],
                                "organization_id": row[5],
                                "expires_at": row[6],
                                "used": row[7]
                            }
            except Exception as e:
                logger.warning(f"Error querying link token from DB: {e}")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        if not token_info:
            return False, "❌ Invalid link token. Please check the code or generate a new one with `!link`."

        if token_info.get("used"):
            return False, "❌ This link token has already been redeemed."

        expires_at = token_info.get("expires_at")
        if isinstance(expires_at, datetime) and datetime.now(timezone.utc) > expires_at:
            return False, "⏳ This link token has expired. Please generate a new one on your other platform with `!link`."

        init_plat = token_info.get("initiating_platform", "").lower()
        targ_plat = target_platform.lower()
        if init_plat == targ_plat:
            return False, f"⚠️ This token was already generated on {targ_plat.capitalize()}. Please redeem it on a different platform (Discord, Slack, or Telegram)."

        # Map channel type enum
        try:
            ch_type = ChannelType(targ_plat)
        except ValueError:
            return False, f"Unsupported channel platform: {target_platform}"

        person_id = token_info["person_id"]
        try:
            identity_service.link_account(
                organization_id=org_id,
                person_id=person_id,
                channel_type=ch_type,
                account_id=str(target_account_id),
                link_type=LinkVerificationType.CLAIMED_UNVERIFIED,
                confidence=0.85,
                username=target_username,
                display_name=target_display_name or target_username,
                evidence={"linked_via_token": clean_token, "source_platform": init_plat}
            )
        except Exception as e:
            logger.error(f"Failed to link account via token {clean_token}: {e}")
            return False, f"❌ Failed to link account: {e}"

        # Mark token as used
        token_info["used"] = True
        conn = self._get_db_conn()
        if conn:
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute("UPDATE account_link_tokens SET used = TRUE WHERE token = %s;", (clean_token,))
            except Exception as e:
                logger.warning(f"Failed to mark token used in DB: {e}")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        return True, (
            f"🎉 **Account Successfully Linked!**\n\n"
            f"Your **{target_platform.capitalize()}** account (`@{target_username}`) is now connected to your "
            f"community profile (originating from **{init_plat.capitalize()}** as `@{token_info['initiating_username']}`).\n"
            f"Your conversation memory, access permissions, and roles are now synchronized across platforms!"
        )


account_link_tool = AccountLinkTool()
