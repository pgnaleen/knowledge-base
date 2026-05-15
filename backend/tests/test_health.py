"""Test health check endpoints — Phase 2."""

import pytest


@pytest.mark.asyncio
async def test_health_liveness(client):
    """Test /health endpoint (liveness probe)."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_readiness(client):
    """Test /health/ready endpoint (readiness probe)."""
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] in ["ready", "ok"]


@pytest.mark.asyncio
async def test_security_headers_present(client):
    """Test that security headers are present in responses."""
    response = client.get("/health")

    assert "x-content-type-options" in response.headers or "X-Content-Type-Options" in response.headers
    assert response.headers.get("x-content-type-options", "").lower() == "nosniff" or \
           response.headers.get("X-Content-Type-Options") == "nosniff"

    assert "x-frame-options" in response.headers or "X-Frame-Options" in response.headers
    assert response.headers.get("x-frame-options", "").upper() == "DENY" or \
           response.headers.get("X-Frame-Options") == "DENY"

    assert "strict-transport-security" in response.headers or "Strict-Transport-Security" in response.headers
