"""Test /chat endpoint with full integration."""

import pytest


@pytest.mark.asyncio
async def test_chat_endpoint_success(client, mock_kb_client, mock_openai_client):
    """Test successful /chat request."""
    response = client.post("/chat", json={"question": "What is ABSD?"})

    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert data["answer"] is not None
    assert len(data["answer"]) > 0


@pytest.mark.asyncio
async def test_chat_endpoint_invalid_question(client):
    """Test /chat with empty question."""
    response = client.post("/chat", json={"question": ""})
    assert response.status_code == 422  # Unprocessable Entity (validation error)


@pytest.mark.asyncio
async def test_chat_endpoint_missing_question(client):
    """Test /chat with missing question field."""
    response = client.post("/chat", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_endpoint_question_too_long(client):
    """Test /chat with question > 2000 chars."""
    response = client.post("/chat", json={"question": "a" * 2001})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_endpoint_sets_session_cookie(client):
    """Test that /chat sets httponly session cookie."""
    response = client.post("/chat", json={"question": "What is ABSD?"})

    assert response.status_code == 200
    assert "session_id" in response.cookies

    # Verify cookie attributes (httponly, samesite)
    # Note: TestClient doesn't fully expose cookie attributes,
    # but we can at least verify the cookie exists
    session_id = response.cookies.get("session_id")
    assert session_id is not None
    assert len(session_id) > 0  # Should be a UUID
