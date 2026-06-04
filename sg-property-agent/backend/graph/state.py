"""Shared state definition for the multi-agent property advisory graph."""

from typing import Annotated

from langgraph.graph.message import add_messages
from typing_extensions import NotRequired, TypedDict


def _keep_last(existing: str | None, new: str | None) -> str | None:
    """
    Reducer for specialist result fields (eligibility_result, financial_result,
    advisory_result). Allows parallel Send agents to each "write" to their own
    result field in the same superstep without raising InvalidUpdateError.

    Semantics: keep the most recent non-None write; None is treated as "no update"
    so an agent that didn't write its result doesn't clobber one that did.
    """
    return new if new is not None else existing


def _merge_completed(existing: list | None, new: list | None) -> list:
    """
    Reducer for completed_agents that supports two operations:
    - Reset: orchestrator writes None  → returns []
    - Accumulate: agents write ["agent_name"] → merges into existing list

    This allows parallel agents (Send fan-out) to each write their own name
    in the same superstep without a conflict, while still letting the
    orchestrator clear the list at the start of each new turn.
    """
    if new is None:
        return []
    return (existing or []) + new


class GraphState(TypedDict):
    # ── Core (required by all agents) ──────────────────────────────────────
    messages: Annotated[list, add_messages]

    # ── Set by Orchestrator on every request ────────────────────────────────
    detected_language: NotRequired[str]   # "en", "zh", "ms", "ta"
    english_query:     NotRequired[str]   # question normalised to English for RAG
    intent:            NotRequired[str]   # see OrchestratorDecision.intent values

    # ── Multi-agent routing ─────────────────────────────────────────────────
    agent_plan:       NotRequired[list]                            # e.g. ["eligibility", "financial"]
    completed_agents: NotRequired[Annotated[list, _merge_completed]] # agents that have finished
    execution_mode:   NotRequired[str]    # "single" | "parallel" | "full"

    # ── Structured outputs per specialist agent ─────────────────────────────
    # Annotated with _keep_last so parallel Send agents can each write their own
    # result field in the same superstep without raising InvalidUpdateError.
    #
    # Eligibility Agent → JSON: {eligible, reasons, property_types, conditions}
    eligibility_result: NotRequired[Annotated[str, _keep_last]]

    # Financial Agent → JSON: {affordable, bsd, absd, tdsr_ok, msr_ok,
    #                           ltv, downpayment, cpf_usable, grants, monthly_payment}
    financial_result: NotRequired[Annotated[str, _keep_last]]

    # Knowledge + Advisory Agent → RAG text with citations + recommendation
    advisory_result: NotRequired[Annotated[str, _keep_last]]
