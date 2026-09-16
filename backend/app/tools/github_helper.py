import os
import json
import logging
from typing import Dict, Any, Optional, List

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
        """Fetch authoritative bound repository for organization. Fails closed if DB binding unavailable."""
        conn = self._get_db_conn()
        if not conn:
            if os.getenv("THREAD_ALLOW_OFFLINE_BINDINGS") == "1":
                return {
                    "repository_name": self._default_repo,
                    "url": f"https://github.com/{self._default_repo}",
                    "is_active": True,
                }
            return {
                "repository_name": None,
                "url": None,
                "is_active": False
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

        if os.getenv("THREAD_ALLOW_OFFLINE_BINDINGS") == "1":
            return {
                "repository_name": self._default_repo,
                "url": f"https://github.com/{self._default_repo}",
                "is_active": True,
            }

        return {
            "repository_name": None,
            "url": None,
            "is_active": False
        }

    def get_recent_commits(self, org_id: str = "gdg_mcet", count: int = 5) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch exact real commits from the server-bound GitHub API repository.
        Returns None if connection/API is unavailable.
        """
        repo_info = self.get_bound_repository(org_id)
        repo_name = repo_info.get("repository_name")
        if not repo_name or not repo_info.get("is_active"):
            return None

        url = f"https://api.github.com/repos/{repo_name}/commits?per_page={count}"
        headers = {
            "User-Agent": "ThreadAgent",
            "Accept": "application/vnd.github.v3+json"
        }
        token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            import urllib.request
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    if isinstance(data, list):
                        commits = []
                        for item in data[:count]:
                            sha = item.get("sha", "")[:7]
                            commit_obj = item.get("commit", {})
                            msg = commit_obj.get("message", "").split("\n")[0]
                            author_obj = commit_obj.get("author", {})
                            author_name = author_obj.get("name") or (item.get("author", {}) or {}).get("login", "Unknown")
                            date_str = author_obj.get("date", "")
                            commits.append({
                                "sha": sha,
                                "message": msg,
                                "author": author_name,
                                "date": date_str,
                                "url": f"https://github.com/{repo_name}/commit/{sha}"
                            })
                        return commits
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch GitHub commits for {repo_name}: {e}")
            return None

    def requested_commit_count(self, query: str = "") -> int:
        """Return the bounded commit count requested by a repository query."""
        q_lower = (query or "").lower()
        count = 5
        import re
        num_match = re.search(r"\b(\d+)\b", q_lower)
        if "latest" in q_lower or "last commit" in q_lower or "1 commit" in q_lower or "one commit" in q_lower:
            if not num_match or num_match.group(1) == "1":
                count = 1
            elif num_match:
                count = int(num_match.group(1))
        elif "five" in q_lower or "last 5" in q_lower or "5 commits" in q_lower:
            count = 5
        elif num_match:
            count = int(num_match.group(1))
        return max(1, min(count, 20))

    def format_github_response(
        self,
        repo_info: Dict[str, Any],
        query: str = "",
        org_id: str = "gdg_mcet",
        commits: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Format GitHub repository status or commit history response."""
        repo_name = repo_info.get("repository_name")
        if not repo_name or not repo_info.get("is_active"):
            return "No authoritative GitHub repository binding is currently configured for this organization."

        q_lower = (query or "").lower()
        is_commit_query = any(k in q_lower for k in ("commit", "commits", "history", "latest", "recent"))

        if is_commit_query:
            count = self.requested_commit_count(query)
            if commits is None:
                commits = self.get_recent_commits(org_id=org_id, count=count)

            if commits is None:
                return "GitHub connection is currently unavailable. Unable to fetch repository commits."

            if not commits:
                return f"No commits found for repository **{repo_name}**."

            exact_commits = commits[:count]
            lines = [f"🐙 **Recent GitHub Commits for [{repo_name}](https://github.com/{repo_name})** (showing {len(exact_commits)}):\n"]
            for idx, c in enumerate(exact_commits, 1):
                author = c.get("author") or "Unknown"
                date_str = c.get("date") or ""
                if date_str and "T" in date_str:
                    date_str = date_str.split("T")[0]
                date_part = f" on {date_str}" if date_str else ""
                commit_sha = c.get("sha")
                commit_url = c.get("url") or f"https://github.com/{repo_name}/commit/{commit_sha}"
                lines.append(f"{idx}. [`{commit_sha}`]({commit_url}) - **{c.get('message')}** *(by {author}{date_part})*")

            return "\n".join(lines)

        repo_url = repo_info.get("url") or f"https://github.com/{repo_name}"

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
