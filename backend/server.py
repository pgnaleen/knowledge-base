"""FastAPI server: /chat and /reset endpoints with session isolation."""

import os
import uuid

from dotenv import load_dotenv
from fastapi import Cookie, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from schemas import ChatRequest, ChatResponse, HealthResponse, ReadyResponse, ResetResponse
from session import SessionStore

load_dotenv()

app = FastAPI(title="SG Property Agent", version="1.0.0")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# CORS from environment, default to Vite dev server
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cors_origins],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Session store: manages per-user PropertyAgent instances
_sessions = SessionStore(max_sessions=500, ttl_seconds=1800)


class ChatRequest(BaseModel):
    """POST /chat request."""

    question: str = Field(..., min_length=1, max_length=2000)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe."""
    return HealthResponse(status="ok")


@app.get("/health/ready", response_model=ReadyResponse)
async def health_ready() -> ReadyResponse:
    """Readiness probe. Checks KB-Pipeline connectivity."""
    # For now, just return ok. In Phase 3 we'll add actual KB-Pipeline health check.
    return ReadyResponse(status="ready")


@app.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest, response: Response, session_id: str = Cookie(default=None)
) -> ChatResponse:
    """Answer a property question with session isolation."""
    # Create or reuse session
    sid = session_id or str(uuid.uuid4())
    agent = _sessions.get_or_create(
        sid,
        kb_url=os.environ["KB_PIPELINE_URL"],
        openai_api_key=os.environ["OPENAI_API_KEY"],
    )

    # Chat (now async)
    answer = await agent.chat(req.question)

    # Set session cookie (httponly, 30-minute TTL)
    response.set_cookie(
        "session_id",
        sid,
        httponly=True,
        samesite="lax",
        max_age=1800,
        path="/",
    )
    return ChatResponse(answer=answer)


@app.post("/reset", response_model=ResetResponse)
async def reset(response: Response, session_id: str = Cookie(default=None)) -> ResetResponse:
    """Reset conversation history for the current session."""
    if session_id:
        _sessions.reset(session_id)
    return ResetResponse(status="ok")
