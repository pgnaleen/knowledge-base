"""
AG05 — Multi-turn conversation state test.

Verifies that buyer details provided in turn 1 are remembered in turn 2.

WHY completed_agents is the correct assertion (not regex on answer text):
  The eligibility agent has two execution paths with different Command.goto values:

  Clarify path  → Command(goto=END)          — citizenship missing
                   completed_agents is NEVER WRITTEN → stays []

  Full path     → Command(goto="orchestrator") — all fields present
                   completed_agents IS WRITTEN  → ["eligibility_agent"]

  Asserting "eligibility_agent" in completed_agents is a structural proof
  that the agent found citizenship from turn 1 and ran the full eligibility check.
  No phrase matching needed.

KB gate caveat:
  If KB is empty, the KB gate fires BEFORE param extraction:
    if "No relevant" in policy_context: return Command(goto=END)
  This also leaves completed_agents=[] — indistinguishable from clarify path via text.
  Tests skip automatically when KB is empty; they pass once KB is populated.

Requires: full stack running (docker compose up + KB populated)
Run:
    docker exec sg-property-backend sh -c \
      "python -m pytest /app/testing/agent/e2e/test_multiturn_context.py -v --tb=short 2>&1"
"""

import uuid

import httpx
import pytest

BACKEND = "http://localhost:8001"
INSPECT_ENDPOINT = f"{BACKEND}/chat/inspect"
TIMEOUT = 90

KB_EMPTY_SIGNAL = "wasn't able to find"  # KB gate message from all three agents


def call_inspect(question: str, thread_id: str) -> dict:
    r = httpx.post(
        INSPECT_ENDPOINT,
        json={"question": question, "thread_id": thread_id},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def _kb_empty(result: dict) -> bool:
    return KB_EMPTY_SIGNAL in result.get("answer", "").lower()


@pytest.mark.level3
def test_ag05_citizenship_remembered_across_turns():
    """
    Turn 1: user provides citizenship — no property question yet.
    Turn 2: property question, same thread_id.
    Pass condition: completed_agents contains "eligibility_agent", proving the agent
    ran its FULL path (all critical fields were found — including citizenship from turn 1).
    """
    thread_id = f"ag05-{uuid.uuid4().hex[:8]}"

    # Turn 1: personal details only (no property type → agent may ask or acknowledge)
    result1 = call_inspect(
        "I am a Singapore Citizen, 35 years old and married.",
        thread_id,
    )
    assert result1.get("intent") is not None, "Turn 1 returned no intent"

    # Turn 2: property question — same thread_id loads the checkpoint
    # Query includes property type ("BTO flat" → hdb_new) so both critical fields
    # can be resolved: citizenship from turn 1, property_type from this query.
    result2 = call_inspect(
        "Can I buy a 4-room HDB BTO flat?",
        thread_id,
    )

    assert result2["intent"] == "eligibility", (
        f"Expected intent=eligibility, got '{result2['intent']}'. "
        f"Answer: {result2.get('answer', '')[:200]}"
    )

    if _kb_empty(result2):
        pytest.skip(
            "KB is empty — KB gate fired before param extraction. "
            "Populate KB (run pipeline with CLOSESPIDER_PAGECOUNT=10) then re-run."
        )

    # CORRECT assertion: structural proof that agent ran its full path
    assert "eligibility_agent" in result2["completed_agents"], (
        f"Eligibility agent did NOT complete its full path. "
        f"completed_agents={result2['completed_agents']}. "
        f"This means citizenship was NOT found in conversation history — "
        f"multi-turn context was NOT preserved. "
        f"Answer: {result2.get('answer', '')[:300]}"
    )


@pytest.mark.level3
def test_ag05_income_remembered_across_turns():
    """
    Turn 1: user provides monthly income.
    Turn 2: financial question, same thread_id.
    Pass condition: completed_agents contains "financial_agent", proving income was used
    from turn 1 (financial agent ran its full path, not the clarify path).
    """
    thread_id = f"ag05b-{uuid.uuid4().hex[:8]}"

    # Turn 1: income only
    call_inspect("My monthly household income is $8,000.", thread_id)

    # Turn 2: financial question — also supplies property price and citizenship so only
    # income is the multi-turn field being tested here
    result2 = call_inspect(
        "I am a Singapore Citizen. Can I afford a $600,000 condo?",
        thread_id,
    )

    if _kb_empty(result2):
        pytest.skip(
            "KB empty — financial agent KB gate fired. "
            "Populate KB with IRAS source then re-run."
        )

    assert result2["intent"] in ("financial", "eligibility_financial"), (
        f"Expected financial or eligibility_financial, got '{result2['intent']}'"
    )

    assert "financial_agent" in result2["completed_agents"], (
        f"Financial agent did NOT complete its full path. "
        f"completed_agents={result2['completed_agents']}. "
        f"Income context from turn 1 was likely not preserved."
    )


@pytest.mark.level3
def test_ag05_different_thread_ids_are_isolated():
    """
    Thread A establishes 'foreigner' citizenship.
    Thread B asks an eligibility question with a different thread_id.
    Pass condition: thread B does NOT complete the full eligibility path —
    it should take the clarify path (missing citizenship) because it has no
    context from thread A.
    """
    thread_a = f"ag05-a-{uuid.uuid4().hex[:8]}"
    thread_b = f"ag05-b-{uuid.uuid4().hex[:8]}"

    # Thread A: establish citizenship
    call_inspect("I am a foreigner from the UK.", thread_a)

    # Thread B: same property question, completely different thread
    result_b = call_inspect(
        "Can I buy a 4-room HDB BTO flat?",
        thread_b,
    )

    if _kb_empty(result_b):
        pytest.skip(
            "KB empty — KB gate and clarify path both produce completed_agents=[]. "
            "Cannot distinguish thread isolation without KB."
        )

    # Thread B should NOT have completed the full path (no citizenship in its own history)
    # If isolation is broken, thread B would have foreigner citizenship from thread A
    # → full path would run → "eligibility_agent" would appear in completed_agents
    assert "eligibility_agent" not in result_b["completed_agents"], (
        f"Thread B ran the full eligibility path — citizenship may have leaked from thread A. "
        f"completed_agents={result_b['completed_agents']}"
    )
