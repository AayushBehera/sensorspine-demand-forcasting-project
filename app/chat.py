"""AI chat entry point.

Delegates to app.llm.get_provider() which returns either the deterministic
FallbackProvider (works with no API key) or a real LLM provider (when env
credentials are present). Both return the `{text, blocks}` contract consumed
by the chat frontend.

Kept intentionally small — all intelligence lives in app/llm.py and app/tools.py.
"""
from __future__ import annotations

from typing import Any

from . import llm


def ask(message: str, history: list[dict] | None = None) -> dict:
    """Return {"text", "blocks", "engine"} for the chat UI."""
    provider = llm.get_provider()
    try:
        result = provider.respond(message, history)
    except Exception as exc:  # never leak raw traces to the client
        return {"text": f"Sorry, the assistant hit an error: {exc}",
                "blocks": [], "engine": provider.name}
    result["engine"] = provider.name
    return result


def groq_status() -> bool:
    """True when a real LLM provider is configured (vs the fallback)."""
    return llm.get_provider().name != "fallback"


def sections() -> list[dict]:
    """Suggested prompts for the chat UI's starter chips."""
    return [
        {"title": "Demand", "q": "What is the demand outlook for the last 30 days?"},
        {"title": "Surplus", "q": "Where is the highest shortage risk this week?"},
        {"title": "Redistribution", "q": "Show pending redistribution recommendations"},
        {"title": "Weather", "q": "What's the live weather at campus-01 and how does it affect demand?"},
        {"title": "Food context", "q": "Show India food context: HCES shares and nutrition"},
        {"title": "Model", "q": "How accurate is the forecasting model?"},
        {"title": "Map", "q": "Show the Bengaluru campus and demand map"},
        {"title": "Explore", "q": "Show me the latest 50 data records"},
    ]
