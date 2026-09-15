import os
import logging
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.memory.conversation import conversation_store

logger = logging.getLogger("thread.tools.summarizer")

class SummarizerAssistant:
    """
    Channel and conversation summarizer tool (!summary).
    Extracts key discussion points, decisions made, and pending action items from
    recent conversation turns or ingested channel records.
    """
    def __init__(self):
        pass

    def summarize_conversation(self, session_key: str, limit: int = 15) -> str:
        """
        Summarize the recent multi-turn conversation in the given session.
        """
        turns = conversation_store.get_recent_turns(session_key, limit=limit)
        if not turns:
            return (
                "📝 **Discussion Summary**\n\n"
                "There is no recent active conversation history in this thread/channel to summarize yet. "
                "Ask questions or discuss topics with the agent, then use `!summary` to catch up!"
            )

        # Format transcript
        lines = []
        for t in turns:
            role_label = "User" if t["role"] == "user" else "Thread Agent"
            lines.append(f"{role_label}: {t['content']}")
        transcript = "\n".join(lines)

        from app.graph.workflow import get_llm
        llm = get_llm()
        if llm:
            prompt = f"""You are an executive meeting & conversation summarizer for GDG MCET.
Analyze the following recent conversation transcript and produce a structured Markdown summary.

Include:
- 📌 **Main Topics Discussed** (1-3 bullet points)
- 💡 **Key Decisions & Takeaways** (1-3 bullet points)
- 🚀 **Next Steps / Action Items** (if applicable)

Keep the summary concise, objective, and easy to skim.

Conversation Transcript:
{transcript}
"""
            try:
                res = llm.invoke(prompt)
                content = res.content if hasattr(res, "content") else str(res)
                return f"📝 **Recent Discussion Summary:**\n\n{content}"
            except Exception as e:
                logger.warning(f"LLM summarization failed: {e}")

        # Deterministic fallback summary
        return (
            f"📝 **Recent Discussion Summary ({len(turns)} turns):**\n\n"
            f"- **Recent Topic**: {turns[-1]['content'][:120]}...\n"
            f"- **Participant Count**: Multi-turn dialogue between community member and Thread Agent.\n"
            f"- **Last Response**: {turns[-1]['role']} at {len(turns)} recorded turns."
        )


summarizer_assistant = SummarizerAssistant()
