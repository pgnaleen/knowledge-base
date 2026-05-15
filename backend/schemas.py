"""Pydantic schemas for request/response validation."""

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    """POST /chat request."""

    question: str = Field(..., min_length=1, max_length=2000, description="User's question about Singapore property")

    @field_validator("question")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        """Strip leading/trailing whitespace and reject empty questions."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("Question cannot be empty or whitespace-only")
        return stripped


class ChatResponse(BaseModel):
    """POST /chat response."""

    answer: str = Field(..., description="Agent's answer grounded in KB-Pipeline context")


class ResetResponse(BaseModel):
    """POST /reset response."""

    status: str = Field(..., description="Status message")


class HealthResponse(BaseModel):
    """GET /health response."""

    status: str = Field(..., description="Service health status")


class ReadyResponse(BaseModel):
    """GET /health/ready response."""

    status: str = Field(..., description="Readiness status")
