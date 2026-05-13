"""FastAPI server: /chat and /reset endpoints."""

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent import PropertyAgent

load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

_agent = PropertyAgent(
    kb_url=os.environ["KB_PIPELINE_URL"],
    anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
)


class ChatRequest(BaseModel):
    """POST /chat request."""

    question: str


@app.post("/chat")
def chat(req: ChatRequest) -> dict:
    """Answer a property question."""
    answer = _agent.chat(req.question)
    return {"answer": answer}


@app.post("/reset")
def reset() -> dict:
    """Reset conversation history."""
    _agent.reset()
    return {"status": "ok"}
