import os
import json
import logging
from typing import Dict, Any, Optional

from app.core.config import settings

logger = logging.getLogger("thread.tools.github")

class GitHubHelper:
    """
    GitHub Helper tool (!github).
    Provides repository status, official repository links, branch policies,
    and open-source contribution instructions for community members.
    """
    def __init__(self):
        self._default_repo = "MdTowfikomer/Thread_agent"

    def _get_db_conn(self):
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if not db_url:
            return None
        try:
            import psycopg2
            return psycopg2.connect(db_url)
        except Exception as e:
            logger.warning(f"Failed to connect to database for github helper: {e}")
            return None

    def get_bound_repository(self, org_id: str = "gdg_mcet") -> Dict[str, Any]:
        """Fetch authoritative bound repository for organization."""
        conn = self._get_db_conn()
        if not conn:
            return {
                "repository_name": self._default_repo,
                "url": f"https://github.com/{self._default_repo}",
                "is_active": True,
            }

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT repository_name, metadata, is_active
                        FROM github_repository_bindings
                        WHERE organization_id = %s AND is_active = TRUE
                        LIMIT 1;
                    """, (org_id,))
                    row = cur.fetchone()
                    if row:
                        meta = row[1] if isinstance(row[1], dict) else (json.loads(row[1]) if row[1] else {})
                        full_name = meta.get("full_name") or row[0]
                        return {
                            "repository_name": full_name,
                            "url": f"https://github.com/{full_name}",
                            "is_active": row[2],
                        }
        except Exception as e:
            logger.warning(f"Failed to query github_repository_bindings: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return {
            "repository_name": self._default_repo,
            "url": f"https://github.com/{self._default_repo}",
            "is_active": True,
        }

    def format_github_response(self, repo_info: Dict[str, Any]) -> str:
        """Format GitHub repository and contribution guide."""
        repo_name = repo_info.get("repository_name", self._default_repo)
        repo_url = repo_info.get("url", f"https://github.com/{repo_name}")

        return (
            f"🐙 **Official GDG MCET GitHub Repository**\n\n"
            f"**Repository**: [{repo_name}]({repo_url})\n\n"
            f"### 🛠 How to Contribute:\n"
            f"1. **Fork or Clone**: `git clone {repo_url}.git`\n"
            f"2. **Create a Feature Branch**: `git checkout -b feat/your-feature-name`\n"
            f"3. **Local Setup**: Install requirements and activate Python virtual environment (`.venv`)\n"
            f"4. **Run Verification**: `pytest` (ensure all tests pass before committing)\n"
            f"5. **Submit a PR**: Open a Pull Request referencing any related issues with clear release notes.\n\n"
            f"*(Tip: Tag @ThreadAgent with specific questions about recent PRs or commits!)*"
        )


github_helper = GitHubHelper()
