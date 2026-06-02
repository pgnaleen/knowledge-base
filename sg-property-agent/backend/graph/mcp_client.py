"""Shared async MCP client — used by all three specialist agents.

Retry strategy (two layers):
  Server-side (knowledge.py in mcp-server): retries KB-Pipeline on 5xx / network errors
  Client-side (here): retries the MCP server connection itself on connection failures
                      (e.g., mcp-server container restarting, brief network blip)

Client-side: 2 attempts, 1s backoff — enough to survive a container restart,
not so many that it hangs the agent for too long.
"""

import asyncio
import json
import os
from typing import Any, Optional

import structlog
from langchain_core.tools import StructuredTool
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel
from pydantic import Field as PydanticField
from pydantic import create_model

log = structlog.get_logger()

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8002/mcp")

_MAX_RETRIES = 2
_RETRY_BACKOFF = 1.0  # seconds between attempts


async def call_tool(tool_name: str, params: dict[str, Any]) -> Any:
    """
    Call an MCP tool on the sg-property-tools server and return the parsed result.

    Returns the parsed JSON result (dict/list) if the tool returns JSON,
    or raw text if not. Raises RuntimeError if all retry attempts fail.

    Args:
        tool_name: Name of the MCP tool (e.g. 'calculate_bsd', 'query_knowledge_base')
        params: Tool input parameters as a dict
    """
    last_exc: Exception = RuntimeError("No attempts made")

    for attempt in range(_MAX_RETRIES):
        try:
            async with streamablehttp_client(MCP_SERVER_URL) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, params)

            if result.isError:
                raise RuntimeError(f"MCP tool '{tool_name}' returned an error: {result.content}")

            if not result.content:
                return ""

            # FastMCP puts each item in a separate content block (e.g. KB returns N chunks
            # as N blocks). Single-block responses (calculators) are returned as-is.
            if len(result.content) == 1:
                raw = result.content[0].text
                try:
                    return json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    return raw
            else:
                parsed = []
                for block in result.content:
                    raw = block.text if hasattr(block, "text") else ""
                    try:
                        parsed.append(json.loads(raw))
                    except (json.JSONDecodeError, TypeError):
                        parsed.append(raw)
                return parsed

        except Exception as exc:
            last_exc = exc
            log.warning("mcp_call_failed", tool=tool_name, attempt=attempt + 1, error=str(exc))

            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(_RETRY_BACKOFF)

    raise RuntimeError(
        f"MCP tool '{tool_name}' failed after {_MAX_RETRIES} attempts: {last_exc}"
    ) from last_exc


# ── Tool discovery ────────────────────────────────────────────────────────────

_SCHEMA_TYPE_MAP: dict[str, type] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}


async def list_tools(prefix: str | None = None) -> list[StructuredTool]:
    """Fetch all tools from the MCP server as LangChain StructuredTools.

    Args:
        prefix: If provided, only return tools whose names start with this string.
                Use "calculate_" for financial calculators, "query_" for KB tools.
    """
    async with streamablehttp_client(MCP_SERVER_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()

    tools = []
    for t in result.tools:
        if prefix and not t.name.startswith(prefix):
            continue
        tools.append(_to_langchain_tool(t))

    log.info("mcp_tools_loaded", count=len(tools), prefix=prefix or "all")
    return tools


def _to_langchain_tool(t: Any) -> StructuredTool:
    """Convert a single MCP tool definition to a LangChain StructuredTool."""
    tool_name = t.name

    async def _fn(**kwargs: Any) -> Any:
        return await call_tool(tool_name, kwargs)

    _fn.__name__ = tool_name

    return StructuredTool.from_function(
        coroutine=_fn,
        name=tool_name,
        description=t.description or tool_name,
        args_schema=_build_args_schema(tool_name, t.inputSchema or {}),
    )


def _build_args_schema(name: str, schema: dict) -> type[BaseModel]:
    """Build a Pydantic model from a JSON Schema dict for use as args_schema."""
    props = schema.get("properties", {})
    required_set = set(schema.get("required", []))
    fields: dict[str, Any] = {}

    for field_name, field_def in props.items():
        py_type = _SCHEMA_TYPE_MAP.get(field_def.get("type", "string"), str)
        desc = field_def.get("description", "")
        if field_name in required_set:
            fields[field_name] = (py_type, PydanticField(..., description=desc))
        else:
            default = field_def.get("default")
            fields[field_name] = (Optional[py_type], PydanticField(default=default, description=desc))

    return create_model(f"{name}_args", **fields)
