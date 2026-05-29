"""SG Property Tools — MCP server exposing financial calculators and KB retrieval.

Tools exposed:
  query_knowledge_base   — hybrid search across all 7 property knowledge sources
  calculate_bsd          — Buyer's Stamp Duty (progressive bracket)
  calculate_absd         — Additional BSD (2023 rates, citizenship + property count)
  calculate_tdsr         — Total Debt Servicing Ratio (55% MAS threshold)
  calculate_msr          — Mortgage Servicing Ratio (30%, HDB/EC only)
  calculate_ltv          — Loan-to-Value limits (HDB vs bank loan)
  calculate_cpf_withdrawal — CPF OA withdrawal limit (lease-based proration)
  calculate_hdb_grants   — EHG / PHG / Family Grant eligibility

Transport: streamable-http (required for Docker/containerised deployment).
Port: 8002 (internal only — not exposed to the internet).
"""

from mcp.server.fastmcp import FastMCP

from tools.calculators import (
    calculate_absd,
    calculate_bsd,
    calculate_cpf_withdrawal,
    calculate_hdb_grants,
    calculate_ltv,
    calculate_msr,
    calculate_tdsr,
)
from tools.knowledge import query_knowledge_base

mcp = FastMCP("sg-property-tools", log_level="INFO", host="0.0.0.0", port=8002)
# ── Register tools ────────────────────────────────────────────────────────────

mcp.tool()(query_knowledge_base)
mcp.tool()(calculate_bsd)
mcp.tool()(calculate_absd)
mcp.tool()(calculate_tdsr)
mcp.tool()(calculate_msr)
mcp.tool()(calculate_ltv)
mcp.tool()(calculate_cpf_withdrawal)
mcp.tool()(calculate_hdb_grants)

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
