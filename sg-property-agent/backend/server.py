"""
FastAPI entry point for SG Property Advisor backend.

Endpoints:
  GET  /health                  → liveness check
  POST /chat                    → SSE token stream (web frontend)
  POST /reset                   → clear conversation memory for a session
  GET  /webhooks/whatsapp       → Meta webhook verification
  POST /webhooks/whatsapp       → incoming WhatsApp messages

Middleware stack (LIFO registration — last added runs first on each request):
  1. CORSMiddleware              (added first → innermost, runs last)
  2. RequestLoggingMiddleware    (added second)
  3. SecurityHeadersMiddleware   (added third)
  4. InputSanitizationMiddleware (added last → outermost, runs FIRST on every request)
"""

import json
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from channels.whatsapp.router import create_whatsapp_router
from graph.main import app as graph_app
from graph.main import reset as graph_reset
from graph.main import stream as graph_stream
from middleware import (
    InputSanitizationMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from schemas import ChatRequest, HealthResponse, ResetRequest

load_dotenv()

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="SG Property Advisor API",
    description="Multi-agent Singapore residential property advisory system.",
    version="2.0.0",
    docs_url="/docs",
    redoc_url=None,
)

# ── Middleware (LIFO — register in reverse run order) ─────────────────────────

_cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]

# CORSMiddleware added first → innermost → runs last
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# RequestLogging added second
app.add_middleware(RequestLoggingMiddleware)

# SecurityHeaders added third
app.add_middleware(SecurityHeadersMiddleware)

# InputSanitization added last → outermost → runs FIRST (pre-LLM gate)
app.add_middleware(InputSanitizationMiddleware)

# ── WhatsApp router ───────────────────────────────────────────────────────────

app.include_router(create_whatsapp_router(), prefix="/webhooks/whatsapp")

# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    """
    Stream the agent response as Server-Sent Events.

    Each SSE event contains a plain text token chunk.
    The client reconstructs the full reply by concatenating all chunks.

    Format:
        data: <token>\n\n

    The stream ends when the connection closes (no explicit [DONE] event).
    """
    async def generate():
        try:
            async for token in graph_stream(req.question, req.thread_id):
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception:
            yield f"data: {json.dumps({'type': 'error', 'text': 'Something went wrong. Please try again.'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering for SSE
        },
    )


@app.post("/reset")
async def reset(req: ResetRequest) -> dict:
    """Clear conversation memory and token budget for a session."""
    graph_reset(req.thread_id)
    return {"status": "ok", "thread_id": req.thread_id}


@app.post("/chat/inspect")
async def chat_inspect(req: ChatRequest) -> dict:
    """
    Testing/debug endpoint — NOT for production use.

    Runs the full agent graph synchronously and returns routing metadata
    alongside the final answer. Allows tests to assert on exactly which
    intent was detected and which agents were invoked, without guessing
    from response content.

    Returns:
        intent:            orchestrator's classified intent (e.g. "financial")
        agents_called:     specialist agents that were planned to run
        completed_agents:  specialist agents that actually completed
        answer:            the final text response from the graph
        error:             present only when graph raised an unhandled exception
    """
    from langchain_core.messages import AIMessage, HumanMessage

    config = {"configurable": {"thread_id": req.thread_id}}
    try:
        result = await graph_app.ainvoke(
            {"messages": [HumanMessage(content=req.question)]},
            config,
        )
    except Exception as exc:
        return {
            "intent": "error",
            "agents_called": [],
            "completed_agents": [],
            "answer": "",
            "error": f"{type(exc).__name__}: {exc}",
        }

    answer = ""
    for msg in reversed(result.get("messages", [])):
        if isinstance(msg, AIMessage):
            answer = msg.content
            break

    return {
        "intent": result.get("intent", "unknown"),
        "agents_called": result.get("agent_plan", []),
        "completed_agents": result.get("completed_agents", []),
        "answer": answer,
        "retrieved_chunks": {
            "eligibility": result.get("eligibility_chunks") or [],
            "financial":   result.get("financial_chunks") or [],
            "advisory":    result.get("advisory_chunks") or [],
        },
    }
