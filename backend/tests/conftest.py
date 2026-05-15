"""Pytest configuration and fixtures."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Mock KB-Pipeline before importing the app
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("KB_PIPELINE_URL", "http://localhost:8000")
os.environ.setdefault("OPENAI_MODEL", "gpt-4o")


@pytest.fixture
def mock_kb_client(monkeypatch):
    """Mock KBPipelineClient.retrieve to return test chunks."""
    from client import Chunk

    async def mock_retrieve(self, query: str, top_k: int = 5):
        return [
            Chunk(
                text="ABSD rates: SC 0%, PR 5%, Foreign 60%",
                source_url="https://iras.gov.sg/absd",
                title="IRAS ABSD Rates",
                score=0.95,
            ),
            Chunk(
                text="HDB eligibility: Must be Singapore Citizen",
                source_url="https://www.hdb.gov.sg/eligibility",
                title="HDB Eligibility",
                score=0.87,
            ),
        ]

    monkeypatch.setattr("client.KBPipelineClient.retrieve", mock_retrieve)
    return mock_retrieve


@pytest.fixture
def mock_openai_client(monkeypatch):
    """Mock AsyncOpenAI.chat.completions.create to return test response."""

    class MockMessage:
        content = "ABSD for a foreign buyer is 60% of the property price."

    class MockChoice:
        message = MockMessage()

    class MockUsage:
        prompt_tokens = 150
        completion_tokens = 42
        total_tokens = 192

    class MockResponse:
        choices = [MockChoice()]
        usage = MockUsage()

    async def mock_create(**kwargs):
        return MockResponse()

    async def mock_init(self, api_key):
        pass

    monkeypatch.setattr("agent.AsyncOpenAI.__init__", mock_init)
    monkeypatch.setattr("agent.AsyncOpenAI.chat.completions.create", mock_create)
    return mock_create


@pytest.fixture
async def client(mock_kb_client, mock_openai_client):
    """FastAPI TestClient with mocked dependencies."""
    from server import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def mock_agent(mock_kb_client, mock_openai_client):
    """Mock PropertyAgent for unit tests."""
    from agent import PropertyAgent

    agent = PropertyAgent(
        kb_url="http://localhost:8000",
        openai_api_key="test-key",
    )
    return agent
