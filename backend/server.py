"""FastAPI server: /chat and /reset endpoints with session isolation."""

import os
import uuid

from dotenv import load_dotenv
from fastapi import Cookie, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from logging_config import get_logger, setup_logging
from middleware import RequestLoggingMiddleware
from schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    ReadyResponse,
    ResetResponse,
    StampDutyRequest,
    StampDutyResponse,
    SSDRequest,
    SSDResponse,
)
from tools.stamp_duty import BuyerProfile, PropertyType, calculate_ssd, calculate_stamp_duty
import json
from fastapi.responses import StreamingResponse
from graph import run as graph_run, reset as graph_reset, stream as graph_stream
from channels.whatsapp.router import create_whatsapp_router

load_dotenv()
setup_logging()  # Initialize structured logging

log = get_logger(__name__)

app = FastAPI(title="SG Property Agent", version="1.0.0", redirect_slashes=False)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
        return response


# Middleware stack (LIFO order: last added = first executed)
app.add_middleware(RequestLoggingMiddleware)  # Log all requests first
app.add_middleware(SecurityHeadersMiddleware)  # Add security headers

# CORS from environment, default to Vite dev server
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cors_origins],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Mount WhatsApp webhook channel
_whatsapp_router = create_whatsapp_router()
app.include_router(_whatsapp_router, prefix="/webhook/whatsapp", tags=["whatsapp"])


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
    """Answer a property question, maintaining conversation history per session."""
    sid = session_id or str(uuid.uuid4())
    answer = await graph_run(thread_id=sid, question=req.question)
    response.set_cookie(
        "session_id",
        sid,
        httponly=True,
        samesite="lax",
        max_age=1800,
        path="/",
    )
    return ChatResponse(answer=answer)


@app.post("/chat/stream")
async def chat_stream(
    req: ChatRequest, response: Response, session_id: str = Cookie(default=None)
):
    """Stream graph execution as Server-Sent Events for the web frontend."""
    sid = session_id or str(uuid.uuid4())

    async def event_generator():
        try:
            async for event_dict in graph_stream(thread_id=sid, question=req.question):
                yield f"data: {json.dumps(event_dict)}\n\n"
        except Exception as exc:
            log.error("chat_stream_error", session_id=sid, error=str(exc))
            yield f"data: {json.dumps({'type': 'error', 'text': 'Stream error. Please try again.'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    streaming_response = StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
    streaming_response.set_cookie(
        "session_id", sid, httponly=True, samesite="lax", max_age=1800, path="/"
    )
    return streaming_response


@app.post("/reset", response_model=ResetResponse)
async def reset_chat(response: Response, session_id: str = Cookie(default=None)) -> ResetResponse:
    """Clear conversation history for the current session."""
    if session_id:
        graph_reset(session_id)
    response.delete_cookie("session_id")
    return ResetResponse(status="ok")


@app.post("/calculate/stamp-duty", response_model=StampDutyResponse)
async def calculate_stamp_duty_endpoint(req: StampDutyRequest) -> StampDutyResponse:
    """Calculate BSD + ABSD for a Singapore property purchase.

    Returns breakdown by BSD tier and total duty amount.
    """
    result = calculate_stamp_duty(
        price=req.purchase_price,
        buyer_profile=BuyerProfile(req.buyer_profile),
        property_type=PropertyType(req.property_type),
    )

    log.info(
        "stamp_duty_calculated",
        purchase_price=req.purchase_price,
        buyer_profile=req.buyer_profile,
        total_duty=result.total,
    )

    return StampDutyResponse(
        bsd=result.bsd,
        absd=result.absd,
        absd_rate=result.absd_rate,
        total=result.total,
        breakdown=[
            {
                "tier_limit": tier["tier_limit"],
                "rate": tier["rate"],
                "taxable_amount": tier["taxable_amount"],
                "duty": tier["duty"],
            }
            for tier in result.breakdown
        ],
        effective_rate=result.effective_rate,
    )


@app.post("/calculate/ssd", response_model=SSDResponse)
async def calculate_ssd_endpoint(req: SSDRequest) -> SSDResponse:
    """Calculate SSD (Seller's Stamp Duty) based on holding period.

    SSD is only payable if sold within 3 years of purchase.
    """
    result = calculate_ssd(sale_price=req.sale_price, holding_years=req.holding_years)

    log.info(
        "ssd_calculated",
        sale_price=req.sale_price,
        holding_years=req.holding_years,
        ssd_amount=result.ssd,
    )

    return SSDResponse(
        ssd=result.ssd,
        ssd_rate=result.ssd_rate,
        sale_price=result.sale_price,
        note=result.note,
    )


@app.on_event("startup")
async def startup_event():
    """Log startup."""
    log.info(
        "server_startup",
        llm_provider=os.environ.get("LLM_PROVIDER", "openai"),
        llm_model=(
            os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
            if os.environ.get("LLM_PROVIDER", "openai").lower() == "openrouter"
            else os.environ.get("OPENAI_MODEL", "gpt-4o")
        ),
        kb_url=os.environ.get("KB_PIPELINE_URL"),
        cors_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173"),
    )
