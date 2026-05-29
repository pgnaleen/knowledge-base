"""
Shared LLM builder — used by all agents in the graph.

Each agent role maps to its own env var so models can be tuned independently
to balance cost vs capability:

  ORCHESTRATOR_MODEL      → routing + synthesis only          → cheaper (e.g. gpt-4o-mini)
  ELIGIBILITY_MODEL       → rule-based eligibility reasoning  → capable (e.g. gpt-4o)
  FINANCIAL_MODEL         → financial calculations + rules    → capable (e.g. gpt-4o)
  KNOWLEDGE_ADVISORY_MODEL→ deep RAG + advisory reasoning     → capable (e.g. gpt-4o)

OpenRouter equivalents (set LLM_PROVIDER=openrouter):
  ORCHESTRATOR_MODEL=meta-llama/llama-3.1-8b-instruct:free
  ELIGIBILITY_MODEL=meta-llama/llama-3.3-70b-instruct:free
  FINANCIAL_MODEL=meta-llama/llama-3.3-70b-instruct:free
  KNOWLEDGE_ADVISORY_MODEL=meta-llama/llama-3.3-70b-instruct:free
"""

import os
from typing import Literal

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

AgentRole = Literal["orchestrator", "eligibility", "financial", "knowledge_advisory"]

_OPENAI_DEFAULTS: dict[str, str] = {
    "orchestrator":       "gpt-4o-mini",
    "eligibility":        "gpt-4o",
    "financial":          "gpt-4o",
    "knowledge_advisory": "gpt-4o",
}

_OPENROUTER_DEFAULTS: dict[str, str] = {
    "orchestrator":       "meta-llama/llama-3.1-8b-instruct:free",
    "eligibility":        "meta-llama/llama-3.3-70b-instruct:free",
    "financial":          "meta-llama/llama-3.3-70b-instruct:free",
    "knowledge_advisory": "meta-llama/llama-3.3-70b-instruct:free",
}

_ROLE_ENV_VARS: dict[str, str] = {
    "orchestrator":       "ORCHESTRATOR_MODEL",
    "eligibility":        "ELIGIBILITY_MODEL",
    "financial":          "FINANCIAL_MODEL",
    "knowledge_advisory": "KNOWLEDGE_ADVISORY_MODEL",
}


def build_llm(role: AgentRole, streaming: bool = True) -> ChatOpenAI:
    """Build a ChatOpenAI client for the given agent role."""
    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    defaults = _OPENROUTER_DEFAULTS if provider == "openrouter" else _OPENAI_DEFAULTS
    model = os.getenv(_ROLE_ENV_VARS[role], defaults[role])

    if provider == "openrouter":
        return ChatOpenAI(
            model=model,
            temperature=0,
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            streaming=streaming,
        )

    return ChatOpenAI(
        model=model,
        temperature=0,
        api_key=os.environ["OPENAI_API_KEY"],
        streaming=streaming,
    )
