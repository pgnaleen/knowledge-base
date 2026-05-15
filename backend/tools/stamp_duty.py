"""Singapore stamp duty calculator.

Implements BSD (Buyer's Stamp Duty), ABSD (Additional Buyer's Stamp Duty),
and SSD (Seller's Stamp Duty) calculations per IRAS 2023 rates.

Reference: https://www.iras.gov.sg/taxes/property-taxes/stamp-duty
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class BuyerProfile(str, Enum):
    """Buyer profile for ABSD determination."""

    SC_FIRST = "sc_first"  # Singapore Citizen, 1st property
    SC_SECOND = "sc_second"  # Singapore Citizen, 2nd property
    SC_THIRD_PLUS = "sc_third_plus"  # Singapore Citizen, 3rd+ property
    PR_FIRST = "pr_first"  # Permanent Resident, 1st property
    PR_SECOND_PLUS = "pr_second_plus"  # Permanent Resident, 2nd+ property
    FOREIGNER = "foreigner"  # Non-SC, Non-PR individual
    COMPANY = "company"  # Entity / company buyer


class PropertyType(str, Enum):
    """Property classification for BSD purposes."""

    RESIDENTIAL = "residential"
    NON_RESIDENTIAL = "non_residential"


@dataclass
class StampDutyResult:
    """Result of a stamp duty calculation."""

    bsd: float  # Buyer's Stamp Duty
    absd: float  # Additional Buyer's Stamp Duty
    absd_rate: float  # ABSD rate applied (as decimal, e.g., 0.60 for 60%)
    total: float  # BSD + ABSD
    breakdown: list[dict]  # Line-by-line BSD tier breakdown
    effective_rate: float  # (BSD + ABSD) / purchase_price


@dataclass
class SSDResult:
    """Result of a seller's stamp duty calculation."""

    ssd: float  # Seller's Stamp Duty amount
    ssd_rate: float  # SSD rate applied (as decimal)
    sale_price: float  # Original sale price
    note: str  # Contextual note (e.g., "No SSD after year 3")


# ABSD rates per buyer profile (as of Feb 2023)
ABSD_RATES = {
    BuyerProfile.SC_FIRST: 0.00,
    BuyerProfile.SC_SECOND: 0.20,
    BuyerProfile.SC_THIRD_PLUS: 0.30,
    BuyerProfile.PR_FIRST: 0.05,
    BuyerProfile.PR_SECOND_PLUS: 0.30,
    BuyerProfile.FOREIGNER: 0.60,
    BuyerProfile.COMPANY: 0.65,
}


def calculate_bsd(price: float, property_type: PropertyType) -> tuple[float, list[dict]]:
    """Calculate BSD (Buyer's Stamp Duty) using tiered rates.

    Residential BSD rates (effective Feb 2023):
    - First S$180,000: 1%
    - S$180,001 to S$360,000: 2%
    - S$360,001 to S$1,000,000: 3%
    - S$1,000,001 to S$1,500,000: 4%
    - S$1,500,001 to S$3,000,000: 5%
    - Above S$3,000,000: 6%

    Non-residential rates (effective Feb 2023):
    - First S$180,000: 1%
    - S$180,001 to S$360,000: 2%
    - S$360,001 to S$1,000,000: 3%
    - Above S$1,000,000: 4%

    Args:
        price: Purchase price in SGD
        property_type: Residential or non-residential

    Returns:
        Tuple of (total BSD amount, list of tier breakdowns)
    """
    if property_type == PropertyType.RESIDENTIAL:
        tiers = [
            (180_000, 0.01),
            (180_000, 0.02),
            (640_000, 0.03),
            (500_000, 0.04),
            (1_500_000, 0.05),
            (float("inf"), 0.06),
        ]
    else:  # Non-residential
        tiers = [
            (180_000, 0.01),
            (180_000, 0.02),
            (640_000, 0.03),
            (float("inf"), 0.04),
        ]

    remaining = price
    total_bsd = 0.0
    breakdown = []

    for tier_limit, rate in tiers:
        if remaining <= 0:
            break

        taxable_amount = min(remaining, tier_limit)
        tier_duty = taxable_amount * rate
        total_bsd += tier_duty

        breakdown.append(
            {
                "tier_limit": tier_limit,
                "rate": rate,
                "taxable_amount": taxable_amount,
                "duty": tier_duty,
            }
        )

        remaining -= taxable_amount

    return total_bsd, breakdown


def calculate_stamp_duty(
    price: float,
    buyer_profile: BuyerProfile,
    property_type: PropertyType = PropertyType.RESIDENTIAL,
) -> StampDutyResult:
    """Calculate total stamp duty (BSD + ABSD).

    Args:
        price: Purchase price in SGD
        buyer_profile: Buyer's citizenship/residency + property count
        property_type: Residential or non-residential

    Returns:
        StampDutyResult with BSD, ABSD, total, and breakdown

    Raises:
        ValueError: If price is invalid
    """
    if price <= 0:
        raise ValueError("Price must be positive")
    if price > 500_000_000:
        raise ValueError("Price cannot exceed S$500,000,000")

    # Calculate BSD
    bsd, bsd_breakdown = calculate_bsd(price, property_type)

    # Calculate ABSD
    absd_rate = ABSD_RATES[buyer_profile]
    absd = price * absd_rate

    total = bsd + absd
    effective_rate = total / price if price > 0 else 0.0

    return StampDutyResult(
        bsd=round(bsd, 2),
        absd=round(absd, 2),
        absd_rate=absd_rate,
        total=round(total, 2),
        breakdown=bsd_breakdown,
        effective_rate=round(effective_rate, 4),
    )


def calculate_ssd(sale_price: float, holding_years: int) -> SSDResult:
    """Calculate SSD (Seller's Stamp Duty) based on holding period.

    SSD is only payable if the property is sold within 3 years of purchase.

    Rates:
    - Year 1: 12%
    - Year 2: 8%
    - Year 3: 4%
    - After year 3: 0% (no SSD)

    Args:
        sale_price: Property sale price in SGD
        holding_years: Years held (0-3+)

    Returns:
        SSDResult with SSD amount, rate, and contextual note

    Raises:
        ValueError: If inputs are invalid
    """
    if sale_price <= 0:
        raise ValueError("Sale price must be positive")
    if holding_years < 0:
        raise ValueError("Holding years cannot be negative")

    if holding_years >= 3:
        return SSDResult(
            ssd=0.0,
            ssd_rate=0.0,
            sale_price=sale_price,
            note="No SSD payable after holding for 3+ years",
        )

    if holding_years == 0:
        rate = 0.12
        note = "Sold in Year 1 of purchase"
    elif holding_years == 1:
        rate = 0.12
        note = "Sold within 1 year of purchase"
    elif holding_years == 2:
        rate = 0.08
        note = "Sold within 2 years of purchase"
    else:  # holding_years == 3 (should be caught above, but handle for safety)
        rate = 0.04
        note = "Sold in Year 3 of purchase"

    ssd = sale_price * rate
    return SSDResult(
        ssd=round(ssd, 2),
        ssd_rate=rate,
        sale_price=sale_price,
        note=note,
    )
