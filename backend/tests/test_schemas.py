"""Test Pydantic schema validation — Phase 1."""

import pytest
from pydantic import ValidationError

from schemas import ChatRequest


def test_chat_request_valid():
    """Test valid ChatRequest."""
    req = ChatRequest(question="What is ABSD?")
    assert req.question == "What is ABSD?"


def test_chat_request_empty_string():
    """Test that empty string is rejected."""
    with pytest.raises(ValidationError) as exc_info:
        ChatRequest(question="")
    assert "at least 1 character" in str(exc_info.value).lower() or "empty" in str(exc_info.value).lower()


def test_chat_request_whitespace_only():
    """Test that whitespace-only string is rejected after stripping."""
    with pytest.raises(ValidationError) as exc_info:
        ChatRequest(question="   ")
    assert "empty" in str(exc_info.value).lower() or "whitespace" in str(exc_info.value).lower()


def test_chat_request_strips_whitespace():
    """Test that leading/trailing whitespace is stripped."""
    req = ChatRequest(question="  What is ABSD?  ")
    assert req.question == "What is ABSD?"


def test_chat_request_max_length():
    """Test that questions > 2000 chars are rejected."""
    long_question = "a" * 2001
    with pytest.raises(ValidationError) as exc_info:
        ChatRequest(question=long_question)
    assert "at most 2000 characters" in str(exc_info.value).lower()


def test_chat_request_min_max_valid():
    """Test boundary conditions."""
    # Minimum: 1 char
    req1 = ChatRequest(question="a")
    assert req1.question == "a"

    # Maximum: 2000 chars
    req2 = ChatRequest(question="a" * 2000)
    assert len(req2.question) == 2000
