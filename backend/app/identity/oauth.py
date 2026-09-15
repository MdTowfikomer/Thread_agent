import os
import time
import uuid
import json
import logging
from typing import Dict, Optional, Tuple, Any
from datetime import datetime, timezone
import jwt
import requests
from fastapi import HTTPException, status

from app.core.config import settings

logger = logging.getLogger("thread.identity.oauth")

class OAuthStateError(HTTPException):
    """Raised when an OAuth state token is invalid, expired, or already consumed."""
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

class OAuthStatePersistenceError(HTTPException):
    """Raised when OAuth state nonce cannot be durably recorded or consumed in the database."""
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail)

class GitHubOAuthError(HTTPException):
    """Raised when GitHub OAuth exchange or user retrieval fails."""
    def __init__(self, detail: str, status_code: int = status.HTTP_502_BAD_GATEWAY):
        super().__init__(status_code=status_code, detail=detail)

class OAuthStateManager:
    """
    Authoritative state token and single-use nonce manager for OAuth flows.
    Security Guarantees:
    1. Cryptographically binds caller's authenticated person_id and organization_id.
    2. Single-use nonce enforces replay protection.
    3. Short-lived expiration (10 minutes) protects against leaked state URLs.
    """
    def __init__(self):
        # In-memory fallback for hermetic offline testing: nonce -> {person_id, org_id, expires_at, consumed}
        self._nonces: Dict[str, Dict[str, Any]] = {}

    def generate_state_token(
        self,
        person_id: str,
        organization_id: str,
        expires_in_seconds: int = 600
    ) -> str:
        """
        Generates a cryptographically signed state token embedding person_id and organization_id.
        Stores nonce in database to prevent replay attacks.
        Fails closed: raises OAuthStatePersistenceError if durable write fails.
        """
        secret = settings.jwt_secret
        if not secret:
            raise RuntimeError("Cannot generate OAuth state token: THREAD_JWT_SECRET is not configured.")

        now = int(time.time())
        exp = now + expires_in_seconds
        nonce = uuid.uuid4().hex

        payload = {
            "sub": person_id,
            "org": organization_id,
            "nonce": nonce,
            "iat": now,
            "exp": exp,
            "action": "github_oauth_link"
        }

        token = jwt.encode(payload, secret, algorithm=settings.JWT_ALGORITHM)

        # Record nonce in-memory
        self._nonces[nonce] = {
            "person_id": person_id,
            "organization_id": organization_id,
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.fromtimestamp(exp, tz=timezone.utc),
            "consumed_at": None
        }

        # Mirror to PostgreSQL if configured (fail-closed)
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO oauth_state_nonces (
                                nonce, organization_id, person_id, created_at, expires_at, consumed_at
                            ) VALUES (%s, %s, %s, TIMEZONE('utc'::text, NOW()), %s, NULL);
                        """, (nonce, organization_id, person_id, datetime.fromtimestamp(exp, tz=timezone.utc)))
                    conn.commit()
            except Exception as e:
                logger.error(f"Failed to record OAuth state nonce in database: {e}")
                raise OAuthStatePersistenceError(f"Failed to durably record OAuth state nonce: {e}") from e
        elif settings.APP_ENV != "development" and not os.getenv("THREAD_ALLOW_OFFLINE_IDENTITY"):
            raise OAuthStatePersistenceError("Database is required for OAuth state nonce persistence in production.")

        return token

    def validate_and_consume_state_token(self, state_token: str) -> Tuple[str, str]:
        """
        Validates the state token signature, expiration, and single-use nonce.
        Returns: (person_id, organization_id).
        Fails closed on tampering, expiration, or replay attempt.
        """
        if not state_token:
            raise OAuthStateError("Missing required OAuth state parameter.")

        secret = settings.jwt_secret
        if not secret:
            raise RuntimeError("Cannot verify OAuth state token: THREAD_JWT_SECRET is not configured.")

        try:
            payload = jwt.decode(state_token, secret, algorithms=[settings.JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            raise OAuthStateError("OAuth state token has expired. Please restart the account linking process.")
        except jwt.InvalidTokenError:
            raise OAuthStateError("Invalid or tampered OAuth state token.")

        if payload.get("action") != "github_oauth_link":
            raise OAuthStateError("Invalid state token action claim.")

        person_id = payload.get("sub")
        org_id = payload.get("org")
        nonce = payload.get("nonce")

        if not person_id or not org_id or not nonce:
            raise OAuthStateError("Malformed OAuth state token claims.")

        # Replay protection check
        # 1. Database check (mandatory in production when database is configured)
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE oauth_state_nonces
                            SET consumed_at = TIMEZONE('utc'::text, NOW())
                            WHERE nonce = %s AND consumed_at IS NULL AND expires_at > TIMEZONE('utc'::text, NOW())
                            RETURNING nonce;
                        """, (nonce,))
                        row = cur.fetchone()
                        if not row:
                            raise OAuthStateError("OAuth state token has already been consumed or has expired.")
                    conn.commit()
            except OAuthStateError:
                raise
            except Exception as e:
                logger.error(f"Database nonce consumption failed: {e}")
                raise OAuthStatePersistenceError(f"Failed to durably consume OAuth state nonce: {e}") from e
        elif settings.APP_ENV != "development" and not os.getenv("THREAD_ALLOW_OFFLINE_IDENTITY"):
            raise OAuthStatePersistenceError("Database is required for OAuth state nonce validation in production.")
        else:
            # 2. In-memory check for offline development/test mode only
            mem_entry = self._nonces.get(nonce)
            if not mem_entry:
                raise OAuthStateError("OAuth state token nonce is invalid or unknown.")
            if mem_entry["consumed_at"] is not None:
                raise OAuthStateError("OAuth state token has already been consumed.")
            mem_entry["consumed_at"] = datetime.now(timezone.utc)

        return person_id, org_id

    def clear(self):
        self._nonces.clear()

oauth_state_manager = OAuthStateManager()


class GitHubOAuthClient:
    """
    Authoritative server-side client for GitHub OAuth operations.
    Retrieves GitHub user profile and immutable numeric user ID directly from GitHub.
    """
    AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
    ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
    USER_API_URL = "https://api.github.com/user"
    EMAILS_API_URL = "https://api.github.com/user/emails"

    def get_authorization_url(
        self,
        state: str
    ) -> str:
        """Builds GitHub OAuth authorization redirect URL using GITHUB_OAUTH_REDIRECT_URI."""
        client_id = settings.github_client_id
        if not client_id:
            raise GitHubOAuthError(
                "GitHub OAuth is not configured: GITHUB_CLIENT_ID is missing.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        uri = settings.github_oauth_redirect_uri
        params = {
            "client_id": client_id,
            "state": state,
            "scope": "read:user,user:email"
        }
        if uri:
            params["redirect_uri"] = uri

        from urllib.parse import urlencode
        return f"{self.AUTHORIZE_URL}?{urlencode(params)}"

    def exchange_code_for_token(
        self,
        code: str
    ) -> str:
        """
        Exchanges temporary OAuth authorization code for GitHub access token.
        Never executes from client/browser.
        """
        client_id = settings.github_client_id
        client_secret = settings.github_client_secret
        if not client_id or not client_secret:
            raise GitHubOAuthError(
                "GitHub OAuth credentials missing: GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET are required.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code
        }
        uri = settings.github_oauth_redirect_uri
        if uri:
            payload["redirect_uri"] = uri

        try:
            resp = requests.post(
                self.ACCESS_TOKEN_URL,
                headers={"Accept": "application/json"},
                data=payload,
                timeout=10.0
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"GitHub OAuth token exchange failed: {e}")
            raise GitHubOAuthError(f"Failed to exchange OAuth code with GitHub: {e}")

        if "error" in data:
            err_desc = data.get("error_description", data.get("error"))
            logger.error(f"GitHub OAuth returned error: {err_desc}")
            raise GitHubOAuthError(f"GitHub OAuth error: {err_desc}", status_code=status.HTTP_400_BAD_REQUEST)

        access_token = data.get("access_token")
        if not access_token:
            raise GitHubOAuthError("GitHub OAuth response did not contain an access token.")

        return access_token

    def fetch_user_profile(self, access_token: str) -> Dict[str, Any]:
        """
        Retrieves user profile directly from GitHub API using the server-held access token.
        Authoritatively extracts the immutable numeric user ID.
        """
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Thread-Organizational-Context-Agent"
        }

        try:
            resp = requests.get(self.USER_API_URL, headers=headers, timeout=10.0)
            resp.raise_for_status()
            user_data = resp.json()
        except Exception as e:
            logger.error(f"GitHub user profile retrieval failed: {e}")
            raise GitHubOAuthError(f"Failed to retrieve user profile from GitHub: {e}")

        github_numeric_id = user_data.get("id")
        if not github_numeric_id:
            raise GitHubOAuthError("GitHub API response did not contain an immutable numeric user ID.")

        email = user_data.get("email")
        if not email:
            # Fallback to /user/emails if primary email is private in profile
            try:
                mail_resp = requests.get(self.EMAILS_API_URL, headers=headers, timeout=5.0)
                if mail_resp.status_code == 200:
                    emails = mail_resp.json()
                    primary = next((m["email"] for m in emails if m.get("primary") and m.get("verified")), None)
                    if not primary and emails:
                        primary = emails[0].get("email")
                    email = primary
            except Exception:
                pass

        return {
            "account_id": str(github_numeric_id),  # Authoritative immutable numeric ID
            "username": user_data.get("login"),
            "display_name": user_data.get("name") or user_data.get("login"),
            "email": email,
            "raw_user": user_data
        }

github_oauth_client = GitHubOAuthClient()
