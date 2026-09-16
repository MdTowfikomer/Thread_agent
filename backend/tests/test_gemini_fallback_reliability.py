import os
import re
import pytest
from unittest.mock import patch, MagicMock

from app.graph.workflow import (
    FALLBACK_GEMINI_MODELS,
    get_llm,
    invoke_llm_with_fallback,
    synthesis_node
)
from app.graph.state import GraphState


def test_fallback_list_contains_no_retired_gemini_1x_or_2x_models():
    """
    Regression test ensuring FALLBACK_GEMINI_MODELS contains NO retired Gemini 1.x or 2.x model IDs
    (e.g., gemini-1.5-flash, gemini-2.0-flash, gemini-2.5-flash, gemini-2.5-flash-lite).
    """
    retired_patterns = [
        r"gemini-1\.",
        r"gemini-2\.",
        "gemini-1.5",
        "gemini-2.0",
        "gemini-2.5"
    ]

    for model_id in FALLBACK_GEMINI_MODELS:
        for pattern in retired_patterns:
            assert not re.search(pattern, model_id), (
                f"Retired Gemini 1.x or 2.x model ID '{model_id}' found in FALLBACK_GEMINI_MODELS!"
            )

    # Confirm only explicitly supported 3.x fallback models are present
    for model_id in FALLBACK_GEMINI_MODELS:
        assert model_id.startswith("gemini-3."), (
            f"Fallback model '{model_id}' is not a supported 3.x Gemini model."
        )


def test_default_gemini_model_is_gemini_3_6_flash():
    """
    Regression test ensuring default GEMINI_MODEL fallback in workflow is gemini-3.6-flash.
    """
    with patch.dict(os.environ, {}, clear=True):
        with patch("langchain_google_genai.ChatGoogleGenerativeAI") as mock_chat:
            get_llm()
            # If GEMINI_API_KEY is unset in clean env, get_llm returns None
            # Let's test with GEMINI_API_KEY set
    
    with patch.dict(os.environ, {"GEMINI_API_KEY": "test_key", "GEMINI_MODEL": ""}, clear=False):
        with patch("langchain_google_genai.ChatGoogleGenerativeAI") as mock_chat:
            get_llm()
            assert mock_chat.call_count >= 1
            call_kwargs = mock_chat.call_args[1]
            assert call_kwargs.get("model") == "gemini-3.6-flash"


def test_transparent_language_model_unavailable_response_on_provider_failure():
    """
    Ensures that when all LLM providers fail or are unconfigured,
    synthesis_node returns the transparent 'I can't reach the language model right now.' response.
    """
    with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
        with patch("app.graph.workflow.invoke_llm_with_fallback", return_value=None):
            state = GraphState(
                query="What can you do?",
                organization_id="gdg_mcet",
                intent_category="GENERAL_KNOWLEDGE",
                chat_history=[
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi"}
                ]
            )

            result = synthesis_node(state)
            assert result.get("final_answer") == "I can't reach the language model right now. Please try again shortly."
