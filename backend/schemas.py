"""Pydantic schemas for request/response validation."""

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class BuyerProfileEnum(str, Enum):
    """Enum for API request bodies."""

    SC_FIRST = "sc_first"
    SC_SECOND = "sc_second"
    SC_THIRD_PLUS = "sc_third_plus"
    PR_FIRST = "pr_first"
    PR_SECOND_PLUS = "pr_second_plus"
    FOREIGNER = "foreigner"
    COMPANY = "company"


class PropertyTypeEnum(str, Enum):
    """Enum for property type."""

    RESIDENTIAL = "residential"
    NON_RESIDENTIAL = "non_residential"


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


class StampDutyRequest(BaseModel):
    """POST /calculate/stamp-duty request."""

    purchase_price: float = Field(
        ..., gt=0, le=500_000_000, description="Property purchase price in SGD"
    )
    buyer_profile: BuyerProfileEnum = Field(..., description="Buyer's citizenship/residency + property count")
    property_type: PropertyTypeEnum = Field(
        default=PropertyTypeEnum.RESIDENTIAL, description="Residential or non-residential"
    )


class SSDRequest(BaseModel):
    """POST /calculate/ssd request."""

    sale_price: float = Field(..., gt=0, description="Property sale price in SGD")
    holding_years: int = Field(..., ge=0, le=50, description="Years held (0=sold in year 1, 3+=no SSD)")


class BSDBreakdown(BaseModel):
    """Breakdown of BSD calculation by tier."""

    tier_limit: float = Field(..., description="Upper limit of this tier")
    rate: float = Field(..., description="Tax rate for this tier (as decimal)")
    taxable_amount: float = Field(..., description="Amount taxed at this tier")
    duty: float = Field(..., description="Duty amount for this tier")


class StampDutyResponse(BaseModel):
    """POST /calculate/stamp-duty response."""

    bsd: float = Field(..., description="Buyer's Stamp Duty (SGD)")
    absd: float = Field(..., description="Additional Buyer's Stamp Duty (SGD)")
    absd_rate: float = Field(..., description="ABSD rate applied (decimal, e.g., 0.60 for 60%)")
    total: float = Field(..., description="Total duty (BSD + ABSD) in SGD")
    breakdown: list[BSDBreakdown] = Field(..., description="Line-by-line BSD tier breakdown")
    effective_rate: float = Field(..., description="Total duty / purchase price")


class SSDResponse(BaseModel):
    """POST /calculate/ssd response."""

    ssd: float = Field(..., description="Seller's Stamp Duty (SGD)")
    ssd_rate: float = Field(..., description="SSD rate applied (decimal)")
    sale_price: float = Field(..., description="Original sale price (SGD)")
    note: str = Field(..., description="Contextual note (holding period, etc)")
