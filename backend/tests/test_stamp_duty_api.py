"""Test stamp duty API endpoints."""

import pytest


@pytest.mark.asyncio
async def test_stamp_duty_endpoint_success(client):
    """Test POST /calculate/stamp-duty endpoint."""
    response = client.post(
        "/calculate/stamp-duty",
        json={
            "purchase_price": 1_000_000,
            "buyer_profile": "foreigner",
            "property_type": "residential",
        },
    )

    assert response.status_code == 200
    data = response.json()

    # Verify response structure
    assert "bsd" in data
    assert "absd" in data
    assert "absd_rate" in data
    assert "total" in data
    assert "breakdown" in data
    assert "effective_rate" in data

    # Verify calculations
    assert data["absd"] == 600_000  # 60% ABSD for foreigner
    assert data["absd_rate"] == 0.60
    assert data["bsd"] > 0
    assert data["total"] == data["bsd"] + data["absd"]


@pytest.mark.asyncio
async def test_stamp_duty_endpoint_invalid_price(client):
    """Test /calculate/stamp-duty with invalid price."""
    response = client.post(
        "/calculate/stamp-duty",
        json={
            "purchase_price": -1_000_000,
            "buyer_profile": "sc_first",
        },
    )

    # OpenAI/validation should fail
    # Either 422 validation error or error from calculator
    assert response.status_code in [400, 422, 500]


@pytest.mark.asyncio
async def test_stamp_duty_endpoint_missing_field(client):
    """Test /calculate/stamp-duty with missing required field."""
    response = client.post(
        "/calculate/stamp-duty",
        json={
            "buyer_profile": "sc_first",
            # Missing purchase_price
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_stamp_duty_endpoint_different_buyers(client):
    """Test stamp duty calculation for different buyer profiles."""
    price = 1_000_000
    profiles = ["sc_first", "sc_second", "foreigner"]

    responses = []
    for profile in profiles:
        response = client.post(
            "/calculate/stamp-duty",
            json={
                "purchase_price": price,
                "buyer_profile": profile,
            },
        )
        assert response.status_code == 200
        responses.append(response.json())

    # SC_FIRST should have lowest duty (no ABSD)
    # SC_SECOND should have middle (20% ABSD)
    # FOREIGNER should have highest (60% ABSD)
    assert responses[0]["total"] < responses[1]["total"] < responses[2]["total"]


@pytest.mark.asyncio
async def test_ssd_endpoint_year_1(client):
    """Test POST /calculate/ssd for year 1 sale."""
    response = client.post(
        "/calculate/ssd",
        json={
            "sale_price": 1_000_000,
            "holding_years": 0,  # Sold in year 1
        },
    )

    assert response.status_code == 200
    data = response.json()

    # Year 1: 12% SSD
    assert data["ssd"] == 120_000
    assert data["ssd_rate"] == 0.12
    assert data["sale_price"] == 1_000_000
    assert "Year 1" in data["note"] or "year 1" in data["note"].lower()


@pytest.mark.asyncio
async def test_ssd_endpoint_no_ssd(client):
    """Test POST /calculate/ssd for no SSD (held 3+ years)."""
    response = client.post(
        "/calculate/ssd",
        json={
            "sale_price": 1_000_000,
            "holding_years": 4,  # Held 4 years
        },
    )

    assert response.status_code == 200
    data = response.json()

    # 4 years: no SSD
    assert data["ssd"] == 0.0
    assert data["ssd_rate"] == 0.0
    assert "no ssd" in data["note"].lower() or "3+" in data["note"]


@pytest.mark.asyncio
async def test_ssd_endpoint_invalid_years(client):
    """Test /calculate/ssd with invalid holding years."""
    response = client.post(
        "/calculate/ssd",
        json={
            "sale_price": 1_000_000,
            "holding_years": -1,  # Negative
        },
    )

    assert response.status_code == 422  # Validation error
