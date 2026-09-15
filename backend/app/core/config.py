import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# Load .env from backend directory or parent
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

KNOWN_INSECURE_SECRETS = {
    "thread-sec-boundary-key-9f8a2b3c4d5e",
    "thread-dev-secret-key-38a4d7c8",
    "secret",
    "changeme",
    "jwtsecret",
    "defaultsecret",
    "password",
    "12345678",
}

class Settings:
    PROJECT_NAME: str = "Thread"
    VERSION: str = "1.0.0"
    API_PREFIX: str = "/api"
    
    # Environment mode: default production
    APP_ENV: str = os.getenv("APP_ENV", "production")
    
    # LLM Keys
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    
    # Supabase (Optional - fallback to memory store if omitted)
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SECRET_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))
    SUPABASE_PUBLISHABLE_KEY: str = os.getenv("SUPABASE_PUBLISHABLE_KEY", os.getenv("SUPABASE_ANON_KEY", ""))
    
    # Defaults
    DEFAULT_DOMAIN: str = "gdg_mcet"
    EMBEDDING_DIMENSION: int = 768
    DEFAULT_EMBEDDING_MODEL: str = "models/text-embedding-004"
    
    # Authentication & Security Boundary
    @property
    def demo_auth_enabled(self) -> bool:
        return os.getenv("THREAD_DEMO_AUTH_ENABLED", "false").lower() in ("true", "1", "yes")

    @property
    def allow_guest_mode(self) -> bool:
        return os.getenv("THREAD_ALLOW_GUEST_MODE", "false").lower() in ("true", "1", "yes")

    @property
    def is_development(self) -> bool:
        return os.getenv("APP_ENV", "production").lower() == "development"

    @property
    def is_render_free_demo(self) -> bool:
        mode = os.getenv("THREAD_DEPLOYMENT_MODE", "").strip().lower()
        app_env = os.getenv("APP_ENV", "").strip().lower()
        is_render = os.getenv("RENDER", "").strip().lower() == "true"
        return mode == "render_free_demo" or app_env == "render_free_demo" or is_render

    # Default THREAD_JWT_SECRET has been strictly removed
    @property
    def jwt_secret(self) -> str:
        return os.getenv("THREAD_JWT_SECRET", "").strip()

    JWT_ALGORITHM: str = "HS256"

    def validate_production_security(self):
        """
        Fail startup in production when THREAD_JWT_SECRET is absent, weak, or a known development value.
        """
        env = os.getenv("APP_ENV", "production").lower()
        secret = self.jwt_secret

        if env != "development":
            if not secret:
                raise RuntimeError(
                    "Security Startup Failure: THREAD_JWT_SECRET is absent in production. "
                    "A cryptographically strong secret must be supplied via environment variable."
                )
            if len(secret) < 32:
                raise RuntimeError(
                    f"Security Startup Failure: THREAD_JWT_SECRET is too weak ({len(secret)} chars). "
                    "Production secrets must be at least 32 characters long."
                )
            if secret in KNOWN_INSECURE_SECRETS:
                raise RuntimeError(
                    "Security Startup Failure: THREAD_JWT_SECRET is set to a known development or default value. "
                    "You must provide a unique, cryptographically secure production key."
                )
            # Normal production strictly forbids THREAD_START_GATEWAY_BOT; dedicated worker process required.
            # render_free_demo mode permits running Gateway inside single-instance web service under advisory lock.
            if os.getenv("THREAD_START_GATEWAY_BOT", "false").lower() in ("true", "1") and not self.is_render_free_demo:
                raise RuntimeError(
                    "Security Startup Failure: THREAD_START_GATEWAY_BOT is strictly development-only. "
                    "In production, running the Gateway bot inside FastAPI API workers causes duplicate connections; "
                    "production must run the dedicated single-worker process: python -m app.channels.run_gateway"
                )
            if os.getenv("THREAD_ENABLE_GITHUB_WEBHOOK", "true").lower() in ("true", "1", "yes") and not self.github_webhook_secret:
                raise RuntimeError(
                    "Security Startup Failure: GITHUB_WEBHOOK_SECRET is absent in production. "
                    "A cryptographically strong webhook secret must be supplied via environment variable."
                )

    
    # Configured trusted origins (no wildcard CORS!)
    @property
    def allowed_origins(self) -> List[str]:
        raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
        return [origin.strip() for origin in raw.split(",") if origin.strip() and origin.strip() != "*"]

    @property
    def has_gemini(self) -> bool:
        return bool(self.GEMINI_API_KEY)
        
    @property
    def has_openai(self) -> bool:
        return bool(self.OPENAI_API_KEY)

    @property
    def has_supabase(self) -> bool:
        return bool(self.SUPABASE_URL and self.SUPABASE_SERVICE_ROLE_KEY)

    # Discord Webhook & Gateway Ed25519 Cryptographic Verification
    @property
    def discord_public_key(self) -> str:
        return os.getenv("THREAD_DISCORD_PUBLIC_KEY", os.getenv("DISCORD_PUBLIC_KEY", "")).strip()

    @property
    def discord_allowed_guild_ids(self) -> List[str]:
        raw = os.getenv("DISCORD_ALLOWED_GUILD_IDS", os.getenv("THREAD_DISCORD_ALLOWED_GUILD_IDS", "")).strip()
        if not raw:
            return []
        return [gid.strip() for gid in raw.split(",") if gid.strip()]

    @property
    def discord_bot_token(self) -> str:
        return os.getenv("DISCORD_BOT_TOKEN", os.getenv("THREAD_DISCORD_BOT_TOKEN", "")).strip()

    # GitHub Webhook HMAC-SHA256 Secret
    @property
    def github_webhook_secret(self) -> str:
        return os.getenv("GITHUB_WEBHOOK_SECRET", "").strip()

    # GitHub OAuth Application Credentials
    @property
    def github_client_id(self) -> str:
        return os.getenv("GITHUB_CLIENT_ID", "").strip()

    @property
    def github_client_secret(self) -> str:
        return os.getenv("GITHUB_CLIENT_SECRET", "").strip()

    @property
    def github_oauth_redirect_uri(self) -> str:
        return os.getenv("GITHUB_OAUTH_REDIRECT_URI", "").strip()

    # Telegram Webhook & Bot Credentials
    @property
    def telegram_bot_token(self) -> str:
        return os.getenv("THREAD_TELEGRAM_BOT_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()

    @property
    def telegram_webhook_secret(self) -> str:
        return os.getenv("THREAD_TELEGRAM_WEBHOOK_SECRET", os.getenv("TELEGRAM_WEBHOOK_SECRET", "")).strip()

    @property
    def telegram_allowed_chat_ids(self) -> List[str]:
        raw = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", os.getenv("THREAD_TELEGRAM_ALLOWED_CHAT_IDS", "")).strip()
        if not raw:
            return []
        return [cid.strip() for cid in raw.split(",") if cid.strip()]

    # Slack Events API & Bot Credentials
    @property
    def slack_signing_secret(self) -> str:
        return os.getenv("THREAD_SLACK_SIGNING_SECRET", os.getenv("SLACK_SIGNING_SECRET", "")).strip()

    @property
    def slack_bot_token(self) -> str:
        return os.getenv("THREAD_SLACK_BOT_TOKEN", os.getenv("SLACK_BOT_TOKEN", "")).strip()

settings = Settings()
