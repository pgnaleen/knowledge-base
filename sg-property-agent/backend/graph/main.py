"""
Master Graph — assembles all four agents into one executable LangGraph.

Routing overview:
  orchestrator             → eligibility_agent | financial_agent |
                             knowledge_advisory_agent | END
  eligibility_agent        → orchestrator | END
  financial_agent          → orchestrator | END
  knowledge_advisory_agent → orchestrator | END

  All three specialists route back to "orchestrator" on success (Pass 2 synthesis).
  All three specialists can route to END when asking the user for missing info —
  in that case the orchestrator is NOT involved so synthesis is not triggered.

Edge declarations vs Command:
  add_conditional_edges() tells LangGraph the POSSIBLE destinations at compile time
  (required for graph validation, visualization, and the Send parallel API).
  Command(goto=...) returned by each agent overrides these at RUNTIME with the
  actual dynamic destination. Both are needed.

MemorySaver: persists GraphState per thread_id across turns. Without this, agents
cannot read prior conversation history — the missing-info → ask → re-route loop
would be blind on every follow-up message.

Exports for server.py:
  stream(question, thread_id)  → AsyncIterator[str]  — SSE token stream for web
  run(question, thread_id)     → str                 — full reply for WhatsApp
  reset(thread_id)             → None                — clear conversation memory
"""

import os
from typing import AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from graph.eligibility_agent import run_eligibility
from graph.financial_agent import run_financial
from graph.knowledge_advisory_agent import run_knowledge_advisory
from graph.orchestrator import orchestrate
from graph.state import GraphState

# ── Routing functions ─────────────────────────────────────────────────────────
# These are evaluated by LangGraph when validating edges. Command(goto=...) in
# each node handles the actual runtime routing, but these must return valid string
# keys (not the state dict) to avoid TypeError: unhashable type: 'dict'.

def _route_from_orchestrator(state: GraphState) -> str:
    # Mirrors orchestrate() Pass 2 check: all planned agents done → synthesis → END
    agent_plan = state.get("agent_plan") or []
    completed = state.get("completed_agents") or []
    if agent_plan and set(completed) >= set(agent_plan):
        return END

    intent = state.get("intent", "advisory")
    if intent == "chitchat":
        return END
    return {
        "eligibility":           "eligibility_agent",
        "financial":             "financial_agent",
        "advisory":              "knowledge_advisory_agent",
        "eligibility_financial": "eligibility_agent",
        "full":                  "eligibility_agent",
    }.get(intent, "knowledge_advisory_agent")


def _route_from_eligibility(state: GraphState) -> str:
    return "orchestrator" if state.get("eligibility_result") else END


def _route_from_financial(state: GraphState) -> str:
    return "orchestrator" if state.get("financial_result") else END


def _route_from_knowledge_advisory(state: GraphState) -> str:
    return "orchestrator" if state.get("advisory_result") else END


# ── Graph assembly ────────────────────────────────────────────────────────────

_builder = StateGraph(GraphState)

_builder.add_node("orchestrator",             orchestrate)
_builder.add_node("eligibility_agent",        run_eligibility)
_builder.add_node("financial_agent",          run_financial)
_builder.add_node("knowledge_advisory_agent", run_knowledge_advisory)

_builder.set_entry_point("orchestrator")

# ── Edges ─────────────────────────────────────────────────────────────────────
# Declare all possible routing paths. Command(goto=...) in each node picks the
# actual destination at runtime.

# Orchestrator routes to any specialist or END (chitchat + synthesis both end here)
_builder.add_conditional_edges(
    "orchestrator",
    _route_from_orchestrator,
    {
        "eligibility_agent":        "eligibility_agent",
        "financial_agent":          "financial_agent",
        "knowledge_advisory_agent": "knowledge_advisory_agent",
        END:                         END,
    },
)

# All three specialists can return to orchestrator (Pass 2 synthesis)
# or go to END (when asking the user for missing information)
_builder.add_conditional_edges(
    "eligibility_agent",
    _route_from_eligibility,
    {"orchestrator": "orchestrator", END: END},
)

_builder.add_conditional_edges(
    "financial_agent",
    _route_from_financial,
    {"orchestrator": "orchestrator", END: END},
)

_builder.add_conditional_edges(
    "knowledge_advisory_agent",
    _route_from_knowledge_advisory,
    {"orchestrator": "orchestrator", END: END},
)

# ── Compile ───────────────────────────────────────────────────────────────────

_checkpointer = MemorySaver()
app = _builder.compile(checkpointer=_checkpointer)

# ── Token budget ──────────────────────────────────────────────────────────────

TOKEN_LIMIT = int(os.getenv("TOKEN_BUDGET_PER_SESSION", "50000"))
_token_budget: dict[str, int] = {}  # thread_id → cumulative tokens used

_BUDGET_EXCEEDED_MSG = (
    "I'm sorry — this conversation has reached its usage limit. "
    "Please start a new chat to continue."
)


def _is_over_budget(thread_id: str) -> bool:
    return _token_budget.get(thread_id, 0) >= TOKEN_LIMIT


def _add_tokens(thread_id: str, tokens: int) -> None:
    _token_budget[thread_id] = _token_budget.get(thread_id, 0) + tokens


# ── Streaming (web SSE) ───────────────────────────────────────────────────────

async def stream(question: str, thread_id: str) -> AsyncIterator[str]:
    """
    Stream the graph response for the web frontend.

    Two paths:
      Synthesis (Pass 2): orchestrator uses streaming=True LLM → tokens arrive via
        on_chat_model_stream filtered to the "orchestrator" node.
      Chitchat / clarifying questions: structured LLM (streaming=False) → no stream
        events → on_chain_end fallback grabs the final AIMessage and yields it whole.

    Specialist agent LLM calls (streaming=False) are silent — they don't emit
    on_chat_model_stream events so they never reach the frontend.
    """
    if _is_over_budget(thread_id):
        yield _BUDGET_EXCEEDED_MSG
        return

    config = {"configurable": {"thread_id": thread_id}}
    input_state = {"messages": [HumanMessage(content=question)]}
    tokens_this_turn = 0
    streamed = False

    async for event in app.astream_events(input_state, config, version="v2"):
        kind = event.get("event")

        if kind == "on_chat_model_stream":
            # Only stream orchestrator tokens — agents use streaming=False so they're silent
            if event.get("metadata", {}).get("langgraph_node") == "orchestrator":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield chunk.content
                    streamed = True

        elif kind == "on_chat_model_end":
            output = event.get("data", {}).get("output")
            if output and hasattr(output, "usage_metadata") and output.usage_metadata:
                tokens_this_turn += output.usage_metadata.get("total_tokens", 0)

        elif kind == "on_chain_end" and event.get("name") == "LangGraph":
            # Fallback for chitchat + clarifying questions (structured LLM, no stream events)
            if not streamed:
                out = event.get("data", {}).get("output", {})
                msgs = out.get("messages", [])
                for msg in reversed(msgs):
                    if isinstance(msg, AIMessage):
                        yield msg.content
                        streamed = True
                        break

    _add_tokens(thread_id, tokens_this_turn)


# ── Non-streaming (WhatsApp) ──────────────────────────────────────────────────

async def run(question: str, thread_id: str) -> str:
    """
    Run the graph and return the complete final answer.
    Used by the WhatsApp channel which cannot stream.
    """
    if _is_over_budget(thread_id):
        return _BUDGET_EXCEEDED_MSG

    config = {"configurable": {"thread_id": thread_id}}
    input_state = {"messages": [HumanMessage(content=question)]}

    result = await app.ainvoke(input_state, config)

    messages = result.get("messages", [])

    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and getattr(msg, "usage_metadata", None):
            _add_tokens(thread_id, msg.usage_metadata.get("total_tokens", 0))
            break

    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            return msg.content

    return "I'm sorry, I couldn't generate a response. Please try again."


# ── Reset conversation ────────────────────────────────────────────────────────

def reset(thread_id: str) -> None:
    """Clear conversation memory and token budget for a session."""
    _token_budget.pop(thread_id, None)
    if hasattr(_checkpointer, "storage"):
        keys_to_delete = [k for k in _checkpointer.storage if k[0] == thread_id]
        for k in keys_to_delete:
            del _checkpointer.storage[k]
