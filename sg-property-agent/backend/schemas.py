"""Pydantic request/response schemas for the FastAPI server."""

from uuid import uuid4

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    thread_id: str = Field(default_factory=lambda: str(uuid4()))


class ResetRequest(BaseModel):
    thread_id: str


class HealthResponse(BaseModel):
    status: str = "ok"
