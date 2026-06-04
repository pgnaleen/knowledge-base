"""
Financial Agent

Answers "How much does it cost / can I afford it?" questions.

Two parts:
  Part 1 — Deterministic calculators (MCP tools on mcp-server)
    BSD, ABSD, TDSR, MSR, LTV, CPF withdrawal limits, HDB grants
    Called via call_tool() — see mcp-server/tools/calculators.py for implementations.

  Part 2 — Policy retrieval (MCP tool → KB-Pipeline, sources: iras, mas)
    Rules around WHEN calculators apply: ABSD remission conditions, TDSR exceptions,
    LTV adjustments after cooling measures, grant eligibility edge cases.

Flow:
  1. Retrieve financing policy context via MCP
  2. Extract financial params from query + conversation history
  3. If critical params missing → ask user → Command(goto=END)
  4. Run calculators via MCP → collect results
  5. LLM synthesises calculator outputs + retrieved policy → structured JSON result
  6. Write financial_result + Command(goto="orchestrator")
"""

import json
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END
from langgraph.types import Command
from pydantic import BaseModel, Field

from graph.llm import build_llm
from graph.mcp_client import call_tool, list_tools
from graph.state import GraphState

# ── LLM + tool discovery ─────────────────────────────────────────────────────

_llm = build_llm("financial", streaming=False)

# Lazy cache — populated on first agent call (MCP server must be running)
_financial_llm_with_tools = None


async def _get_financial_llm():
    """Return LLM bound to all MCP tools (calculators + KB query)."""
    global _financial_llm_with_tools
    if _financial_llm_with_tools is None:
        try:
            tools = await list_tools()  # all tools: calculate_* + query_*
        except Exception:
            tools = []  # MCP server unavailable — proceed without tools
        _financial_llm_with_tools = _llm.bind_tools(tools)
    return _financial_llm_with_tools

# ── RAG retrieval via MCP ─────────────────────────────────────────────────────

async def _retrieve_financing_policy(english_query: str) -> str:
    """Retrieve financing policy docs from KB via MCP (IRAS + MAS sources)."""
    try:
        chunks: list[dict] = await call_tool(
            "query_knowledge_base",
            {
                "query": english_query,
                "source_filter": ["iras", "mas"],
                "top_k": 5,
                "search_mode": "hybrid",
            },
        )
    except Exception:
        return "No financing policy context available from knowledge base."

    if not chunks:
        return "No relevant financing documents found."

    parts = []
    for i, chunk in enumerate(chunks, 1):
        source = chunk.get("source", "unknown")
        url = chunk.get("url", "")
        text = chunk.get("text", "").strip()
        citation = f"[{source}]({url})" if url else f"[{source}]"
        parts.append(f"[{i}] {citation}\n{text}")

    return "\n\n".join(parts)


# ── Parameter extraction ──────────────────────────────────────────────────────

class FinancialParams(BaseModel):
    property_price: Optional[float] = Field(
        default=None,
        description="Property purchase price in SGD. null if not mentioned.",
    )
    citizenship: Optional[str] = Field(
        default=None,
        description="One of: singapore_citizen, singapore_pr, foreigner, company. null if unknown.",
    )
    property_count: Optional[int] = Field(
        default=None,
        description="Total residential properties owned AFTER this purchase (1=first, 2=second...). null if unknown.",
    )
    monthly_income: Optional[float] = Field(
        default=None,
        description="Gross monthly household income in SGD. null if not mentioned.",
    )
    existing_monthly_debt: Optional[float] = Field(
        default=None,
        description="Existing monthly debt payments (car loans, student loans, etc.) in SGD. 0 if none mentioned.",
    )
    loan_type: Optional[str] = Field(
        default=None,
        description="Preferred loan type: 'hdb' or 'bank'. null if unknown.",
    )
    outstanding_mortgages: Optional[int] = Field(
        default=None,
        description="Number of current outstanding mortgages. null if unknown.",
    )
    cpf_oa_balance: Optional[float] = Field(
        default=None,
        description="CPF Ordinary Account balance in SGD. null if not mentioned.",
    )
    remaining_lease_years: Optional[int] = Field(
        default=None,
        description="Remaining lease of target property in years. null if unknown.",
    )
    flat_type: Optional[str] = Field(
        default=None,
        description="HDB flat type: 2room/3room/4room/5room/executive. null if not applicable.",
    )
    proximity_to_parents: Optional[bool] = Field(
        default=None,
        description="Whether buyer plans to live with or near parents (for PHG). null if unknown.",
    )
    is_hdb_or_ec: Optional[bool] = Field(
        default=None,
        description="True if target property is HDB or EC (needed for MSR). null if unknown.",
    )


_EXTRACT_PROMPT = """\
Extract financial parameters from the FULL conversation history below.
Read ALL prior messages — the user may have provided details in earlier turns.
Return null for any value not determinable from the conversation.
"""

_structured_llm = _llm.with_structured_output(FinancialParams)


def _build_conversation_context(state: GraphState) -> str:
    parts = []
    for msg in state["messages"]:
        role = "User" if isinstance(msg, HumanMessage) else "Assistant"
        parts.append(f"{role}: {msg.content}")
    return "\n".join(parts)


def _find_missing_critical(params: FinancialParams) -> list[str]:
    missing = []
    if params.property_price is None:
        missing.append("property price (in SGD)")
    if params.citizenship is None:
        missing.append("citizenship status (Singapore Citizen / PR / Foreigner) — needed for ABSD calculation")
    return missing


# ── Prompts ───────────────────────────────────────────────────────────────────

_CALC_SELECTOR_PROMPT = """\
You are coordinating financial calculations for a Singapore property purchase.

Based on the extracted buyer parameters below, call ALL applicable financial
calculator tools. Use each tool's description to decide whether it applies
given the available data. Skip any calculator where required parameters are null.

EXTRACTED PARAMETERS:
{params_json}

Call the relevant calculator tools now.
"""

_CLARIFY_PROMPT = """\
You are SG Property Advisor. You need specific financial details to calculate
stamp duties and assess affordability, but some information is missing.

Ask the user a clear, friendly question in {language} to collect only the
missing information. Ask all missing fields in ONE message (numbered list).

MISSING FIELDS:
{missing_fields}

CONTEXT SO FAR:
{context}
"""

_SYNTHESIS_PROMPT = """\
You are SG Property Advisor — a financial analysis specialist for Singapore property.

You have calculator outputs and retrieved financing policy below.
Produce a structured JSON financial summary covering all applicable calculations.

CALCULATOR RESULTS:
{calculator_results}

FINANCING POLICY CONTEXT (from IRAS / MAS sources):
{policy_context}

Return a JSON object with these fields:
{{
  "bsd": {{"amount": ..., "breakdown": "...", "note": "..."}},
  "absd": {{"rate_pct": "...", "amount": ..., "note": "..."}},
  "total_stamp_duty": ...,
  "tdsr": {{"ok": ..., "ratio_pct": "...", "max_monthly_payment": ..., "note": "..."}},
  "msr": {{"applicable": ..., "ok": ..., "note": "..."}},
  "ltv": {{"max_ltv_pct": "...", "max_loan": ..., "note": "..."}},
  "cpf": {{"usable": ..., "note": "..."}},
  "grants": {{"total": ..., "items": [...], "note": "..."}},
  "upfront_cash_needed": ...,
  "key_risks": ["risk 1", "risk 2"],
  "sources_used": ["iras", "mas"]
}}

Rules:
✅ Use ONLY the calculator results and policy context provided
✅ Set "note" to explain any exceptional policy conditions found in the context
✅ If a calculation was not run (missing data), set its value to null with a note
❌ Do not invent numbers not in the calculator results
"""

_FORMAT_PROMPT = """\
You are SG Property Advisor. Summarise this financial analysis for the user.

FINANCIAL ANALYSIS (JSON):
{result_json}

Rules:
✅ Respond in {language}
✅ Lead with total stamp duty cost
✅ State clearly if TDSR/MSR passes or fails
✅ Mention any significant risks or conditions
✅ Keep it under 250 words — precise and actionable
❌ Do not add information not in the JSON above
"""


# ── Agent entry point ─────────────────────────────────────────────────────────

async def run_financial(state: GraphState) -> Command:
    english_query = state.get("english_query") or state["messages"][-1].content
    language = state.get("detected_language", "en")
    conversation_context = _build_conversation_context(state)

    # Step 1: retrieve financing policy context via MCP
    policy_context = await _retrieve_financing_policy(english_query)

    # KB gate — stop before any LLM call if no documents were retrieved.
    # Prevents the model from adding unsupported policy commentary from training memory.
    if "No relevant" in policy_context:
        return Command(
            goto=END,
            update={
                "messages": [AIMessage(content=(
                    "I wasn't able to find relevant financing policy documents in my "
                    "knowledge base for your question."
                ))],
            },
        )

    # Step 2: extract financial params from full conversation history
    # TODO (MCP task): prepend get_user_profile(user_id) result here
    params: FinancialParams = await _structured_llm.ainvoke([
        SystemMessage(content=_EXTRACT_PROMPT),
        HumanMessage(content=conversation_context),
    ])

    # Step 3: check for critical missing information
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

    # Step 4: LLM selects and calls applicable calculators via bound tools
    llm_with_tools = await _get_financial_llm()
    tool_response = await llm_with_tools.ainvoke([
        SystemMessage(content=_CALC_SELECTOR_PROMPT.format(
            params_json=params.model_dump_json(exclude_none=True),
        )),
        HumanMessage(content=english_query),
    ])

    calculator_results: dict[str, Any] = {}
    price = params.property_price or 0

    for tc in tool_response.tool_calls:
        result = await call_tool(tc["name"], tc["args"])
        key = tc["name"].replace("calculate_", "")
        calculator_results[key] = result

    # Derive max_loan from LTV ratio + price (LTV tool returns ratio only)
    if "ltv" in calculator_results and price:
        calculator_results["ltv"]["max_loan"] = round(
            price * calculator_results["ltv"].get("max_ltv", 0)
        )

    # Step 5: LLM synthesises calculator outputs + retrieved policy
    synthesis_response = await _llm.ainvoke([
        SystemMessage(content=_SYNTHESIS_PROMPT.format(
            calculator_results=json.dumps(calculator_results, ensure_ascii=False),
            policy_context=policy_context,
        )),
        HumanMessage(content=english_query),
    ])

    raw = synthesis_response.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        result_dict = json.loads(raw)
    except Exception:
        result_dict = {"summary": raw, "calculator_results": calculator_results}

    result_json = json.dumps(result_dict, ensure_ascii=False)

    # Step 6: format for synthesis layer
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
            "financial_result": result_json,
            "completed_agents": ["financial_agent"],  # reducer merges parallel writes
        },
    )
