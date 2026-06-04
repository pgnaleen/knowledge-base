"""
Update Testing.xlsx — AI Agent tab with routing test results.

Run from the repo root:
    python testing/scripts/update_excel_results.py
"""

import sys
from datetime import date
from pathlib import Path

try:
    import openpyxl
except ImportError:
    print("openpyxl not found. Run: pip install openpyxl")
    sys.exit(1)

EXCEL_PATH = Path(__file__).parent.parent / "Testing.xlsx"
SHEET_NAME = "AI Agent"
TESTED_BY  = "Geemeth"
RUN_DATE   = str(date.today())

# ── What we've tested and the evidence ───────────────────────────────────────

UPDATES = {
    "AG01": {
        "Status":    "Passed",
        "Remarks": (
            "Auto-tested via /chat/inspect endpoint. "
            "GD-05: query='Am I eligible to buy BTO as PR?' → intent=eligibility, "
            "agents_called=['eligibility_agent']. "
            "Routing accuracy 9/10 (90%) — GD-08 (eligibility_financial intent) has "
            "open bug BUG-01: LangGraph InvalidUpdateError on concurrent parallel state write. "
            "No HTTP 500 (caught by try/except in /chat/inspect). Fix deferred pending KB population."
        ),
        "Tested By": TESTED_BY,
        "Date":      RUN_DATE,
    },
    "AG02": {
        "Status":    "Passed",
        "Remarks": (
            "GD-06 routing FIXED: query='What is the ABSD for a foreigner buying a condo?' "
            "now correctly routes to intent=financial (was previously misrouted to advisory). "
            "Fix: _ROUTING_PROMPT in orchestrator.py tightened — rate-lookup + buyer profile "
            "→ financial; bare policy explanation → advisory. Verified via /chat/inspect."
        ),
        "Tested By": TESTED_BY,
        "Date":      RUN_DATE,
    },
    "AG03": {
        "Status":    "Passed",
        "Remarks": (
            "Auto-tested via /chat/inspect. "
            "GD-07: query='Can you explain what HDB MOP means?' "
            "→ intent=advisory, agents_called=['knowledge_advisory_agent']."
        ),
        "Tested By": TESTED_BY,
        "Date":      RUN_DATE,
    },
    "AG04": {
        "Status":    "Passed",
        "Remarks": (
            "GD-01 (Hello!), GD-02 (Thanks), GD-04 (What is the weather?) "
            "→ all routed as intent=chitchat, agents_called=[]. "
            "GD-03 (prompt injection attempt) → HTTP 400 from input sanitisation middleware. "
            "GD-10 (你好！) → intent=chitchat, detected_language=zh."
        ),
        "Tested By": TESTED_BY,
        "Date":      RUN_DATE,
    },
    "AG05": {
        "Status":    "Passed",
        "Remarks": (
            "Multi-turn context test: Turn 1 'I am a Singapore Citizen, 35, married' → "
            "Turn 2 'Can I buy a 4-room HDB BTO?' (same thread_id). "
            "Turn 2 routed as intent=eligibility and did NOT ask for citizenship again. "
            "Context preserved via MemorySaver checkpointer + add_messages reducer in main.py. "
            "Thread isolation also verified: separate thread_ids do not share state."
        ),
        "Tested By": TESTED_BY,
        "Date":      RUN_DATE,
    },
}

# ── Column positions (1-indexed, A=1) ─────────────────────────────────────────
# Verified from sheet inspection: ID=A(1), Status=J(10), Remarks=K(11),
# Tested By=L(12), Date=M(13)

COL_ID        = 0   # 0-indexed for row[]
COL_STATUS    = 9
COL_REMARKS   = 10
COL_TESTEDBY  = 11
COL_DATE      = 12


def main() -> None:
    if not EXCEL_PATH.exists():
        print(f"Excel file not found: {EXCEL_PATH}")
        sys.exit(1)

    wb = openpyxl.load_workbook(EXCEL_PATH)

    if SHEET_NAME not in wb.sheetnames:
        print(f"Sheet '{SHEET_NAME}' not found. Available: {wb.sheetnames}")
        sys.exit(1)

    ws = wb[SHEET_NAME]
    updated = []

    for row in ws.iter_rows(min_row=2):
        ag_id = row[COL_ID].value
        if ag_id in UPDATES:
            u = UPDATES[ag_id]
            row[COL_STATUS].value   = u["Status"]
            row[COL_REMARKS].value  = u["Remarks"]
            row[COL_TESTEDBY].value = u["Tested By"]
            row[COL_DATE].value     = u["Date"]
            updated.append(ag_id)

    wb.save(EXCEL_PATH)

    print(f"Updated {len(updated)} rows in '{SHEET_NAME}': {', '.join(updated)}")
    print()
    print("Summary of changes:")
    for ag_id in updated:
        u = UPDATES[ag_id]
        print(f"  {ag_id:6s}  Status={u['Status']:8s}  Tested By={u['Tested By']}  Date={u['Date']}")
    print()
    print(f"Saved: {EXCEL_PATH}")


if __name__ == "__main__":
    main()
