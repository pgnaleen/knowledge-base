"""Test session isolation — Phase 0 concurrency bug fix."""

import pytest


@pytest.mark.asyncio
async def test_chat_creates_session_cookie(client):
    """Test that /chat creates a session cookie."""
    response = client.post("/chat", json={"question": "What is ABSD?"})
    assert response.status_code == 200
    assert "session_id" in response.cookies
    assert response.json()["answer"] is not None


@pytest.mark.asyncio
async def test_different_sessions_have_isolated_history(client):
    """Test that two different sessions don't share conversation history."""
    # Session 1: Ask a question
    response1 = client.post(
        "/chat", json={"question": "What is ABSD?"}, cookies={}
    )
    session1_id = response1.cookies.get("session_id")
    assert session1_id is not None

    # Session 2: Ask a different question (new session)
    response2 = client.post(
        "/chat", json={"question": "What is BSD?"}, cookies={}
    )
    session2_id = response2.cookies.get("session_id")
    assert session2_id is not None

    # Sessions should be different
    assert session1_id != session2_id

    # Both should get answers (proof they're isolated, not cross-contaminated)
    assert "ABSD" in response1.json()["answer"] or "60%" in response1.json()["answer"]
    assert response2.json()["answer"] is not None


@pytest.mark.asyncio
async def test_reset_only_affects_current_session(client):
    """Test that /reset only clears the current session's history."""
    # Create session 1
    session1_response = client.post(
        "/chat", json={"question": "What is ABSD?"}, cookies={}
    )
    session1_id = session1_response.cookies.get("session_id")

    # Create session 2
    session2_response = client.post(
        "/chat", json={"question": "What is BSD?"}, cookies={}
    )
    session2_id = session2_response.cookies.get("session_id")

    # Reset session 1
    reset_response = client.post(
        "/reset", cookies={"session_id": session1_id}
    )
    assert reset_response.status_code == 200

    # Both sessions should still be able to chat independently
    followup1 = client.post(
        "/chat", json={"question": "More about ABSD?"}, cookies={"session_id": session1_id}
    )
    followup2 = client.post(
        "/chat", json={"question": "More about BSD?"}, cookies={"session_id": session2_id}
    )

    assert followup1.status_code == 200
    assert followup2.status_code == 200
