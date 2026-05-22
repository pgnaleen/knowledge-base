"""LangGraph agent — single entry point for all channels (web + WhatsApp)."""

import os
import time
from typing import Annotated, AsyncGenerator

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from logging_config import get_logger
from tools.retrieve import retrieve_property_info
from tools.stamp_duty_tools import calculate_stamp_duty, calculate_ssd

load_dotenv()
log = get_logger(__name__)


class GraphState(TypedDict):
    messages: Annotated[list, add_messages]
    retrieved_context: str


SYSTEM_PROMPT = (
    "You are SG Property Advisor — an expert AI assistant for Singapore residential property decisions.\n"
    "Your expertise covers: ABSD, BSD, SSD, HDB eligibility, CPF usage, LTV/TDSR limits, and property ownership rules.\n\n"

    "═══════════════════════════════════════════════════════════\n"
    "REASONING FRAMEWORK — Execute for EVERY user message\n"
    "═══════════════════════════════════════════════════════════\n\n"

    "STEP 1 — CLASSIFY THE QUERY\n"
    "A. GREETING / CHITCHAT  (e.g. \"hi\", \"thanks\", \"okay\")\n"
    "   → Respond warmly, invite a property question. Do NOT cite context.\n"
    "B. GENERAL KNOWLEDGE  (e.g. \"What is ABSD?\", \"Explain CPF OA\")\n"
    "   → Answer using ONLY the retrieved context below. Cite sources.\n"
    "C. USER-SPECIFIC ADVISORY  (e.g. \"Can I buy an HDB?\", \"Am I eligible?\")\n"
    "   → If citizenship / marital status / ownership not yet known, ask for them (see Step 2).\n"
    "   → Once you have the details, answer using ONLY the retrieved context. Cite sources.\n"
    "D. CALCULATION REQUEST  (e.g. \"Calculate BSD for $500,000\")\n"
    "   → Call calculate_stamp_duty or calculate_ssd tool. Cite the result.\n\n"

    "STEP 2 — CONTEXT GATHERING (for Type C when personal details are missing)\n"
    "Reply with:\n"
    "\"To give you accurate advice, I need a few details:\n"
    "- Citizenship status: Singapore Citizen, PR, or Foreigner?\n"
    "- Marital status: Single, Married, or Divorced?\n"
    "- Current property ownership: Do you own any property in Singapore?\n"
    "- Property type of interest: HDB (BTO/Resale), Executive Condo, or Private?\n"
    "Please share what applies to you and I will provide a personalised answer with official sources.\"\n\n"

    "STEP 3 — RETRIEVED CONTEXT (official Singapore government sources)\n"
    "{context}\n\n"
    "If the context is empty or irrelevant to the query, say:\n"
    "\"The knowledge base does not contain specific information on [topic]. "
    "Please consult the official HDB, IRAS, URA, MAS, or CPF website.\"\n\n"

    "STEP 4 — TOOL USAGE\n"
    "If the query involves BSD / ABSD / SSD AND the user has provided price + citizenship + property type:\n"
    "→ Call calculate_stamp_duty or calculate_ssd. NEVER compute manually.\n\n"

    "STEP 5 — COMPOSE RESPONSE\n"
    "1. Direct answer (1–2 sentences)\n"
    "2. Cited explanation with inline [1], [2] references\n"
    "3. Sources: numbered list at the end\n\n"

    "═══════════════════════════════════════════════════════════\n"
    "STRICT RULES\n"
    "═══════════════════════════════════════════════════════════\n"
    "✅ Cite every factual claim as [1], [2] etc.\n"
    "✅ Use ONLY retrieved context or tool results — NEVER training knowledge\n"
    "✅ Ask for missing personal details before answering user-specific queries\n"
    "✅ Use tools for all calculations — never compute manually\n"
    "❌ Never guess eligibility, tax rates, or financial figures\n"
    "❌ Never cite sources not present in the retrieved context\n"
    "❌ Never use filler phrases like \"Great question!\" or \"I'd be happy to help\"\n"
)


def _build_llm() -> ChatOpenAI:
    """Build chat model client from env, supporting OpenAI and OpenRouter."""
    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    if provider == "openrouter":
        return ChatOpenAI(
            model=os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-120b:free"),
            temperature=0,
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            streaming=True,
        )
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        temperature=0,
        api_key=os.environ["OPENAI_API_KEY"],
        streaming=True,
    )


_checkpointer = MemorySaver()
_calculator_tools = [calculate_stamp_duty, calculate_ssd]
_tool_node = ToolNode(_calculator_tools)
_llm_with_tools = _build_llm().bind_tools(_calculator_tools)


async def _retrieve(state: GraphState) -> dict:
    question = state["messages"][-1].content
    context = await retrieve_property_info.ainvoke({"query": question})
    return {"retrieved_context": context}


async def _agent(state: GraphState) -> dict:
    context = state["retrieved_context"]
    if context.startswith("Knowledge base unavailable"):
        log.warning("kb_unavailable", reason=context[:80])
        return {"messages": [AIMessage(content=(
            "I'm unable to answer right now because the knowledge base is unavailable. "
            "Please ensure the KB-Pipeline service is running on port 8000 and try again."
        ))]}
    system_prompt = SYSTEM_PROMPT.format(context=context or "(no relevant context retrieved)")
    messages = [SystemMessage(content=system_prompt)] + list(state["messages"])
    response = await _llm_with_tools.ainvoke(messages)
    return {"messages": [response]}


def _should_continue(state: GraphState) -> str:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END


_builder = StateGraph(GraphState)
_builder.add_node("retrieve", _retrieve)
_builder.add_node("agent", _agent)
_builder.add_node("tools", _tool_node)
_builder.set_entry_point("retrieve")
_builder.add_edge("retrieve", "agent")
_builder.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
_builder.add_edge("tools", "agent")
_graph = _builder.compile(checkpointer=_checkpointer)


async def run(thread_id: str, question: str) -> str:
    """Invoke the graph for a given thread. Returns answer string. Used by WhatsApp."""
    log.info("agent_run_start", thread_id=thread_id, question=question[:120])
    t0 = time.monotonic()
    config = {"configurable": {"thread_id": thread_id}}
    result = await _graph.ainvoke(
        {"messages": [HumanMessage(content=question)], "retrieved_context": ""},
        config=config,
    )
    elapsed_ms = round((time.monotonic() - t0) * 1000)
    last_msg = result["messages"][-1]
    usage = getattr(last_msg, "usage_metadata", None)
    log.info(
        "agent_run_done",
        thread_id=thread_id,
        latency_ms=elapsed_ms,
        input_tokens=usage.get("input_tokens") if usage else None,
        output_tokens=usage.get("output_tokens") if usage else None,
        total_tokens=usage.get("total_tokens") if usage else None,
    )
    return last_msg.content


async def stream(thread_id: str, question: str) -> AsyncGenerator[dict, None]:
    """Yield SSE event dicts as the graph executes. Used by /chat/stream endpoint."""
    config = {"configurable": {"thread_id": thread_id}}

    async for event in _graph.astream_events(
        {"messages": [HumanMessage(content=question)], "retrieved_context": ""},
        config=config,
        version="v2",
    ):
        kind = event["event"]
        name = event.get("name", "")

        if kind == "on_chain_start" and name == "retrieve":
            yield {"type": "status", "text": "Searching knowledge base..."}
        elif kind == "on_chain_end" and name == "retrieve":
            yield {"type": "status", "text": "Generating answer..."}
        elif kind == "on_tool_start" and name in ("calculate_stamp_duty", "calculate_ssd"):
            yield {"type": "status", "text": "Calculating..."}
        elif kind == "on_chat_model_stream":
            chunk = event["data"].get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                yield {"type": "token", "content": chunk.content}

    yield {"type": "done"}


def reset(thread_id: str) -> None:
    """Clear conversation history for a thread."""
    storage = _checkpointer.storage
    keys_to_delete = [
        k for k in storage
        if (isinstance(k, tuple) and k[0] == thread_id) or k == thread_id
    ]
    for k in keys_to_delete:
        del storage[k]
