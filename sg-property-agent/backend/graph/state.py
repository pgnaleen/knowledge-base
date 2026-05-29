"""Shared state definition for the multi-agent property advisory graph."""

from typing import Annotated

from langgraph.graph.message import add_messages
from typing_extensions import NotRequired, TypedDict


class GraphState(TypedDict):
    # ── Core (required by all agents) ──────────────────────────────────────
    messages: Annotated[list, add_messages]

    # ── Set by Orchestrator on every request ────────────────────────────────
    detected_language: NotRequired[str]   # "en", "zh", "ms", "ta"
    english_query:     NotRequired[str]   # question normalised to English for RAG
    intent:            NotRequired[str]   # see OrchestratorDecision.intent values

    # ── Multi-agent routing ─────────────────────────────────────────────────
    agent_plan:       NotRequired[list]   # e.g. ["eligibility", "financial"]
    completed_agents: NotRequired[list]   # agents that have finished
    execution_mode:   NotRequired[str]    # "single" | "parallel" | "full"

    # ── Structured outputs per specialist agent ─────────────────────────────
    # Eligibility Agent → JSON: {eligible, reasons, property_types, conditions}
    eligibility_result: NotRequired[str]

    # Financial Agent → JSON: {affordable, bsd, absd, tdsr_ok, msr_ok,
    #                           ltv, downpayment, cpf_usable, grants, monthly_payment}
    financial_result: NotRequired[str]

    # Knowledge + Advisory Agent → RAG text with citations + recommendation
    advisory_result: NotRequired[str]
