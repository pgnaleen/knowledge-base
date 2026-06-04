"""
Eligibility Agent

Answers "Can I buy this property?" using the latest policy from the KB.

Why no hardcoded rules: HDB income ceilings, ABSD rates, MOP rules, and cooling
measures change with each government budget. Hardcoding creates a maintenance
liability and risks returning stale answers.

Flow:
  1. Always retrieve policy docs from KB (source_filter: hdb, ura, top_k=5)
  2. Extract buyer params from current query + full conversation history
     TODO (MCP task): also call get_user_profile(user_id) to pre-fill known params
  3. If critical params still missing → ask user → Command(goto=END)
     (NOT via orchestrator — going through orchestrator would trigger synthesis
     before the user has answered)
  4. LLM reasons over retrieved policy + params → structured eligibility result
  5. Write eligibility_result + Command(goto="orchestrator")

BuyerParams: temporary extraction of what the user has told us in THIS conversation.
This is NOT a stored profile — it only exists during this request.
Future get_user_profile() (MCP) will be a persistent record stored in a database.
"""

import json
from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END
from langgraph.types import Command
from pydantic import BaseModel, Field

from graph.llm import build_llm
from graph.mcp_client import call_tool, list_tools
from graph.state import GraphState

# ── LLM + tool discovery ─────────────────────────────────────────────────────

_llm = build_llm("eligibility", streaming=False)

_eligibility_llm_with_tools = None


async def _get_eligibility_llm():
    """Return LLM bound to KB query tools (query_*)."""
    global _eligibility_llm_with_tools
    if _eligibility_llm_with_tools is None:
        tools = await list_tools(prefix="query_")
        _eligibility_llm_with_tools = _llm.bind_tools(tools)
    return _eligibility_llm_with_tools


# ── RAG retrieval via bound tools ─────────────────────────────────────────────

_RETRIEVE_POLICY_PROMPT = """\
Retrieve Singapore property eligibility policy from the knowledge base.
Call query_knowledge_base with source_filter=['hdb','ura'], top_k=5, search_mode='hybrid'.
"""


async def _retrieve_policy(english_query: str) -> str:
    """Retrieve eligibility-related policy docs from KB via tool-bound LLM."""
    try:
        llm_tools = await _get_eligibility_llm()
        response = await llm_tools.ainvoke([
            SystemMessage(content=_RETRIEVE_POLICY_PROMPT),
            HumanMessage(content=english_query),
        ])
        chunks: list[dict] = []
        for tc in response.tool_calls:
            result = await call_tool(tc["name"], tc["args"])
            if isinstance(result, list):
                chunks.extend(result)
    except Exception:
        return "No policy context available from knowledge base."

    if not chunks:
        return "No relevant policy documents found."

    parts = []
    for i, chunk in enumerate(chunks, 1):
        source = chunk.get("source", "unknown")
        url = chunk.get("url", "")
        text = chunk.get("text", "").strip()
        citation = f"[{source}]({url})" if url else f"[{source}]"
        parts.append(f"[{i}] {citation}\n{text}")

    return "\n\n".join(parts)


# ── Buyer parameter extraction ────────────────────────────────────────────────
# BuyerParams: what the user has told us in this conversation (not a stored profile).
# TODO (MCP task): call get_user_profile(user_id) first to pre-fill known fields,
# then use this extraction only for fields still missing from the profile.

class BuyerParams(BaseModel):
    citizenship: Optional[str] = Field(
        default=None,
        description=(
            "Buyer citizenship. One of: singapore_citizen, singapore_pr, foreigner, company. "
            "null if not determinable from conversation."
        ),
    )
    marital_status: Optional[str] = Field(
        default=None,
        description=(
            "Marital or family nucleus status. One of: "
            "single, married, divorced, widowed, fiancee_scheme. null if not determinable."
        ),
    )
    age: Optional[int] = Field(
        default=None,
        description="Buyer's age in years. null if not mentioned.",
    )
    monthly_income: Optional[float] = Field(
        default=None,
        description="Gross monthly household income in SGD. null if not mentioned.",
    )
    existing_hdb: Optional[bool] = Field(
        default=None,
        description="True if buyer currently owns or has previously owned an HDB flat. null if unknown.",
    )
    existing_private: Optional[bool] = Field(
        default=None,
        description="True if buyer currently owns private residential property. null if unknown.",
    )
    property_type: Optional[str] = Field(
        default=None,
        description=(
            "Target property type. One of: "
            "hdb_new, hdb_resale, ec_new, ec_resale, private_condo, private_landed. "
            "null if not determinable."
        ),
    )
    is_second_property: Optional[bool] = Field(
        default=None,
        description="True if this would be buyer's second or subsequent property. null if unknown.",
    )


_EXTRACT_PROMPT = """\
Extract the buyer's situation from the FULL conversation history below.
Read ALL prior messages — the user may have provided details in earlier turns.
Return null for any field that cannot be determined from the conversation.

NOTE: In a future version, you will also receive a pre-filled user profile from
the database via get_user_profile(). For now, extract only from conversation.
"""

_structured_llm = _llm.with_structured_output(BuyerParams)


def _build_conversation_context(state: GraphState) -> str:
    parts = []
    for msg in state["messages"]:
        role = "User" if isinstance(msg, HumanMessage) else "Assistant"
        parts.append(f"{role}: {msg.content}")
    return "\n".join(parts)


def _find_missing_critical(params: BuyerParams) -> list[str]:
    """Critical fields without which eligibility cannot be determined."""
    missing = []
    if params.citizenship is None:
        missing.append("citizenship status (Singapore Citizen / PR / Foreigner)")
    if params.property_type is None:
        missing.append(
            "type of property you want to buy "
            "(HDB BTO / HDB resale / Executive Condo / private condo / landed)"
        )
    return missing


# ── Prompts ───────────────────────────────────────────────────────────────────

_CLARIFY_PROMPT = """\
You are SG Property Advisor. To check the user's property eligibility, you need
specific information that is not yet in the conversation.

Ask a clear, friendly question in {language} to collect only the missing details.
Ask all missing fields in ONE message (numbered list if multiple).
Do not ask for details already provided in the conversation.

MISSING INFORMATION:
{missing_fields}

CONVERSATION SO FAR:
{context}
"""

_ELIGIBILITY_PROMPT = """\
You are SG Property Advisor — an eligibility specialist for Singapore residential property.

Using the POLICY CONTEXT below (retrieved from official HDB / URA sources), determine
whether the buyer described in BUYER SITUATION can purchase the target property.

BUYER SITUATION:
{params_json}

POLICY CONTEXT:
{policy_context}

Return a JSON object:
{{
  "eligible": true/false/null,
  "confidence": "high" | "medium" | "low",
  "summary": "one-sentence verdict",
  "reasons": ["specific reason from the policy"],
  "conditions": ["condition or requirement they must meet"],
  "alternatives": ["alternative property types they CAN buy if not eligible for target"],
  "sources_used": ["source name"]
}}

Rules:
✅ Base your answer ONLY on the policy context provided
✅ Set eligible=null and confidence=low if the context does not cover the scenario
✅ Be specific — cite actual policy details (e.g. "5-year MOP", "$14,000 income ceiling")
❌ Do not invent eligibility rules not present in the policy context
"""

_FORMAT_PROMPT = """\
You are SG Property Advisor. Summarise this eligibility result for the user.

ELIGIBILITY RESULT (JSON):
{result_json}

Rules:
✅ Respond in {language}
✅ Lead with a clear eligible / not eligible statement
✅ List the key reasons and conditions they must meet
✅ If not eligible, mention what they CAN buy as alternatives
✅ Keep it under 200 words — direct and actionable
❌ Do not add information not in the JSON above
"""


# ── Agent entry point ─────────────────────────────────────────────────────────

async def run_eligibility(state: GraphState) -> Command:
    english_query = state.get("english_query") or state["messages"][-1].content
    language = state.get("detected_language", "en")
    conversation_context = _build_conversation_context(state)

    # Step 1: retrieve latest policy docs (always — no caching on stale rules)
    policy_context = await _retrieve_policy(english_query)

    # KB gate — stop before any LLM call if no documents were retrieved.
    # Prevents the model from answering eligibility questions from training memory.
    if "No relevant" in policy_context:
        return Command(
            goto=END,
            update={
                "messages": [AIMessage(content=(
                    "I wasn't able to find relevant property policy documents in my "
                    "knowledge base for your question."
                ))],
            },
        )

    # Step 2: extract buyer params from full conversation history
    # TODO (MCP task): call get_user_profile(user_id) first, then extract remaining gaps
    params: BuyerParams = await _structured_llm.ainvoke([
        SystemMessage(content=_EXTRACT_PROMPT),
        HumanMessage(content=conversation_context),
    ])

    # Step 3: ask for missing critical info — go directly to END (not orchestrator)
    missing = _find_missing_critical(params)
    if missing:
        clarify_response = await _llm.ainvoke([
            SystemMessage(content=_CLARIFY_PROMPT.format(
                language=language,
                missing_fields="\n".join(f"- {f}" for f in missing),
                context=conversation_context,
            )),
            HumanMessage(content=english_query),
        ])
        return Command(
            goto=END,
            update={"messages": [AIMessage(content=clarify_response.content)]},
        )

    # Step 4: eligibility reasoning over retrieved policy
    params_json = params.model_dump_json(exclude_none=False)
    elig_response = await _llm.ainvoke([
        SystemMessage(content=_ELIGIBILITY_PROMPT.format(
            params_json=params_json,
            policy_context=policy_context,
        )),
        HumanMessage(content=english_query),
    ])

    raw = elig_response.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        result_dict = json.loads(raw)
    except Exception:
        result_dict = {"eligible": None, "summary": raw, "reasons": [], "conditions": []}

    result_json = json.dumps(result_dict, ensure_ascii=False)

    # Step 5: format for synthesis (result stored as-is; orchestrator synthesises final reply)
    await _llm.ainvoke([
        SystemMessage(content=_FORMAT_PROMPT.format(
            result_json=result_json,
            language=language,
        )),
        HumanMessage(content=english_query),
    ])

    return Command(
        goto="orchestrator",
        update={
            "eligibility_result": result_json,
            "completed_agents": ["eligibility_agent"],  # reducer merges parallel writes
        },
    )
