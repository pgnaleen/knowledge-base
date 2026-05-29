"""
Knowledge + Advisory Agent

Two modes detected from GraphState:
  knowledge mode  — eligibility_result AND financial_result are empty
                    → pure RAG: retrieve from KB then answer with citations
  advisory mode   — both populated (agent ran after parallel specialists)
                    → personalised recommendation combining all three data sources

Missing info handling (same pattern as eligibility + financial agents):
  If advisory mode but conversation lacks critical context (e.g. no mention of
  budget, purpose, family situation) → ask user → Command(goto=END)
  User answers → orchestrator re-routes → agent runs fully

Retrieval: direct HTTP POST to KB-Pipeline /retrieve (all 7 sources, hybrid search)
TODO (MCP task): replace _retrieve() with:
    await mcp_client.call_tool("query_knowledge_base",
                               {"query": english_query, "top_k": 7, "search_mode": "hybrid"})
Future MCP tools: recommend_properties(), get_market_analysis(), get_property_valuation()

Routes back to "orchestrator" on success, or END when asking user for more info.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END
from langgraph.types import Command

from graph.llm import build_llm
from graph.mcp_client import call_tool, list_tools
from graph.state import GraphState

# ── LLM + tool discovery ─────────────────────────────────────────────────────

_llm = build_llm("knowledge_advisory", streaming=False)

_knowledge_llm_with_tools = None


async def _get_knowledge_llm():
    """Return LLM bound to KB query tools (query_*)."""
    global _knowledge_llm_with_tools
    if _knowledge_llm_with_tools is None:
        tools = await list_tools(prefix="query_")
        _knowledge_llm_with_tools = _llm.bind_tools(tools)
    return _knowledge_llm_with_tools


# ── Prompts ───────────────────────────────────────────────────────────────────

_KNOWLEDGE_PROMPT = """\
You are SG Property Advisor — an expert on Singapore residential property rules,
regulations, taxes, stamp duties, financing, and transaction processes.

Answer the user's question using ONLY the retrieved context provided below.
Rules:
✅ Cite government sources inline as [Source: <source_name>] after each fact
✅ If the context is insufficient, say so clearly — do not invent information
✅ Respond in {language}
❌ Do not add information not present in the context

RETRIEVED CONTEXT:
{context}
"""

_ADVISORY_PROMPT = """\
You are SG Property Advisor — a senior advisor helping a specific user make an
informed Singapore property purchase decision.

You have completed specialist analyses:

ELIGIBILITY ANALYSIS:
{eligibility_result}

FINANCIAL ANALYSIS:
{financial_result}

ADDITIONAL CONTEXT (from government sources):
{context}

Give a clear, personalised recommendation using ALL of the above.

Structure:
1. Key finding — is the user eligible and can they afford it?
2. Most important considerations (top 2–3)
3. Recommended next steps
4. Cite government sources as [Source: <source_name>] where relevant

Rules:
✅ Respond in {language}
✅ Be direct and actionable
❌ Do not repeat information already in the eligibility/financial results
❌ Do not add facts not present in the specialist results or context
"""

_MISSING_INFO_CHECK_PROMPT = """\
You are reviewing a conversation to determine if there is ENOUGH context to give
a personalised Singapore property recommendation.

For a good recommendation, the user should have mentioned at least SOME of:
- Purpose of purchase (own stay / investment / rental)
- Approximate budget or price range
- Family situation (single, married, kids)
- Location preferences or urgency

CONVERSATION:
{context}

ELIGIBILITY RESULT AVAILABLE: {has_eligibility}
FINANCIAL RESULT AVAILABLE: {has_financial}

If critical context is completely absent AND eligibility + financial results are also
missing, return the specific questions to ask. Otherwise return "SUFFICIENT".

Return either:
  "SUFFICIENT"
  or a short, friendly question in {language} asking for the missing context (1–2 sentences max).
"""

_CLARIFY_PROMPT = """\
You are SG Property Advisor. You have the user's eligibility and financial analysis,
but need a bit more context to give a truly personalised recommendation.

Ask the user a friendly question in {language} to gather:
{missing_context}

Keep it to 1–2 sentences. Be warm and conversational.
"""

# ── RAG retrieval via bound tools ─────────────────────────────────────────────

_RETRIEVE_PROMPT = """\
Retrieve relevant Singapore property knowledge from the knowledge base.
Call query_knowledge_base with top_k=7, search_mode='hybrid' (no source_filter — search all sources).
"""


async def _retrieve(english_query: str) -> str:
    """Fetch relevant knowledge chunks from KB via tool-bound LLM (all 7 sources)."""
    try:
        llm_tools = await _get_knowledge_llm()
        response = await llm_tools.ainvoke([
            SystemMessage(content=_RETRIEVE_PROMPT),
            HumanMessage(content=english_query),
        ])
        chunks: list[dict] = []
        for tc in response.tool_calls:
            result = await call_tool(tc["name"], tc["args"])
            if isinstance(result, list):
                chunks.extend(result)
    except Exception:
        return "No additional context available from knowledge base."

    if not chunks:
        return "No relevant documents found."

    parts = []
    for i, chunk in enumerate(chunks, 1):
        source = chunk.get("source", "unknown")
        url = chunk.get("url", "")
        text = chunk.get("text", "").strip()
        citation = f"[{source}]({url})" if url else f"[{source}]"
        parts.append(f"[{i}] {citation}\n{text}")

    return "\n\n".join(parts)


def _build_conversation_context(state: GraphState) -> str:
    parts = []
    for msg in state["messages"]:
        role = "User" if isinstance(msg, HumanMessage) else "Assistant"
        parts.append(f"{role}: {msg.content}")
    return "\n".join(parts)


# ── Agent entry point ─────────────────────────────────────────────────────────

async def run_knowledge_advisory(state: GraphState) -> Command:
    english_query = state.get("english_query") or state["messages"][-1].content
    language = state.get("detected_language", "en")
    eligibility_result = state.get("eligibility_result", "")
    financial_result = state.get("financial_result", "")
    conversation_context = _build_conversation_context(state)

    advisory_mode = bool(eligibility_result and financial_result)

    # In advisory mode: check if enough personal context exists to give a recommendation.
    # In knowledge mode: retrieval is always sufficient — no missing-info check needed.
    if advisory_mode:
        check_response = await _llm.ainvoke([
            SystemMessage(content=_MISSING_INFO_CHECK_PROMPT.format(
                context=conversation_context,
                has_eligibility="yes" if eligibility_result else "no",
                has_financial="yes" if financial_result else "no",
                language=language,
            )),
            HumanMessage(content=english_query),
        ])
        check_result = check_response.content.strip()

        if check_result.upper() != "SUFFICIENT":
            # Not enough context — ask the user directly, skip orchestrator synthesis
            return Command(
                goto=END,
                update={"messages": [AIMessage(content=check_result)]},
            )

    # Retrieve KB context (always — no stale LLM knowledge)
    context = await _retrieve(english_query)

    if advisory_mode:
        system_prompt = _ADVISORY_PROMPT.format(
            eligibility_result=eligibility_result,
            financial_result=financial_result,
            context=context,
            language=language,
        )
    else:
        system_prompt = _KNOWLEDGE_PROMPT.format(context=context, language=language)

    response = await _llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=english_query),
    ])

    completed = list(state.get("completed_agents") or [])
    completed.append("knowledge_advisory_agent")

    return Command(
        goto="orchestrator",
        update={
            "advisory_result": response.content,
            "completed_agents": completed,
        },
    )
