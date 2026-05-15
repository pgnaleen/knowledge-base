"""Test stamp duty calculator — Phase 9."""

import pytest

from tools.stamp_duty import (
    BuyerProfile,
    PropertyType,
    calculate_bsd,
    calculate_ssd,
    calculate_stamp_duty,
)


class TestBSD:
    """Test BSD calculation."""

    def test_bsd_residential_basic(self):
        """Test BSD for a basic residential property."""
        # Property at S$500,000
        bsd, breakdown = calculate_bsd(500_000, PropertyType.RESIDENTIAL)

        # Should be in the 3% tier
        # S$180k @ 1% = 1,800
        # S$180k @ 2% = 3,600
        # S$140k @ 3% = 4,200
        # Total = 9,600
        assert bsd == 9_600
        assert len(breakdown) == 3  # Only 3 tiers used


    def test_bsd_residential_high_value(self):
        """Test BSD for a high-value residential property."""
        # Property at S$3,500,000 (goes into 6% tier)
        bsd, breakdown = calculate_bsd(3_500_000, PropertyType.RESIDENTIAL)

        # Calculation:
        # 180k @ 1% = 1,800
        # 180k @ 2% = 3,600
        # 640k @ 3% = 19,200
        # 500k @ 4% = 20,000
        # 1,500k @ 5% = 75,000
        # 500k @ 6% = 30,000
        # Total = 149,600
        assert bsd == 149_600
        assert len(breakdown) == 6


    def test_bsd_non_residential(self):
        """Test BSD for non-residential property."""
        # Non-residential property at S$1,500,000
        # Rates: 1%, 2%, 3%, 4%
        bsd, breakdown = calculate_bsd(1_500_000, PropertyType.NON_RESIDENTIAL)

        # 180k @ 1% = 1,800
        # 180k @ 2% = 3,600
        # 640k @ 3% = 19,200
        # 500k @ 4% = 20,000
        # Total = 44,600
        assert bsd == 44_600
        assert len(breakdown) == 4


class TestABSD:
    """Test ABSD calculation."""

    def test_absd_singapore_citizen_first_property(self):
        """Test ABSD for SC buying 1st property (0%)."""
        result = calculate_stamp_duty(
            1_000_000,
            BuyerProfile.SC_FIRST,
            PropertyType.RESIDENTIAL,
        )
        assert result.absd == 0.0
        assert result.absd_rate == 0.0


    def test_absd_singapore_citizen_second_property(self):
        """Test ABSD for SC buying 2nd property (20%)."""
        result = calculate_stamp_duty(
            1_000_000,
            BuyerProfile.SC_SECOND,
            PropertyType.RESIDENTIAL,
        )
        assert result.absd == 200_000
        assert result.absd_rate == 0.20


    def test_absd_foreigner(self):
        """Test ABSD for foreigner buying property (60%)."""
        result = calculate_stamp_duty(
            1_000_000,
            BuyerProfile.FOREIGNER,
            PropertyType.RESIDENTIAL,
        )
        assert result.absd == 600_000
        assert result.absd_rate == 0.60


    def test_absd_company(self):
        """Test ABSD for corporate buyer (65%)."""
        result = calculate_stamp_duty(
            1_000_000,
            BuyerProfile.COMPANY,
            PropertyType.RESIDENTIAL,
        )
        assert result.absd == 650_000
        assert result.absd_rate == 0.65


class TestStampDutyTotal:
    """Test combined BSD + ABSD."""

    def test_total_singapore_citizen_first(self):
        """Test total duty for SC buying 1st property."""
        result = calculate_stamp_duty(
            1_000_000,
            BuyerProfile.SC_FIRST,
            PropertyType.RESIDENTIAL,
        )
        # BSD for 1M: 180k@1% + 180k@2% + 640k@3% = 1,800 + 3,600 + 19,200 = 24,600
        # ABSD: 0%
        # Total: 24,600
        assert result.bsd == 24_600
        assert result.absd == 0.0
        assert result.total == 24_600


    def test_effective_rate(self):
        """Test effective rate calculation."""
        result = calculate_stamp_duty(
            1_000_000,
            BuyerProfile.FOREIGNER,
            PropertyType.RESIDENTIAL,
        )
        # BSD: 24,600
        # ABSD: 600,000
        # Total: 624,600
        # Effective: 624,600 / 1,000,000 = 0.6246
        assert result.total == 624_600
        assert result.effective_rate == 0.6246


    def test_invalid_price_zero(self):
        """Test that zero price is rejected."""
        with pytest.raises(ValueError, match="must be positive"):
            calculate_stamp_duty(0, BuyerProfile.SC_FIRST)


    def test_invalid_price_negative(self):
        """Test that negative price is rejected."""
        with pytest.raises(ValueError, match="must be positive"):
            calculate_stamp_duty(-1_000_000, BuyerProfile.SC_FIRST)


    def test_invalid_price_too_high(self):
        """Test that price > S$500M is rejected."""
        with pytest.raises(ValueError, match="cannot exceed"):
            calculate_stamp_duty(500_000_001, BuyerProfile.SC_FIRST)


class TestSSD:
    """Test Seller's Stamp Duty calculation."""

    def test_ssd_year_1(self):
        """Test SSD for property sold within 1 year (12%)."""
        result = calculate_ssd(1_000_000, holding_years=0)
        assert result.ssd == 120_000
        assert result.ssd_rate == 0.12
        assert "Year 1" in result.note


    def test_ssd_year_2(self):
        """Test SSD for property sold within 2 years (8%)."""
        result = calculate_ssd(1_000_000, holding_years=1)
        assert result.ssd == 120_000  # Still 12% within year 1
        assert result.ssd_rate == 0.12


    def test_ssd_year_3(self):
        """Test SSD for property sold in year 3 (4%)."""
        result = calculate_ssd(1_000_000, holding_years=2)
        assert result.ssd == 80_000
        assert result.ssd_rate == 0.08


    def test_ssd_after_3_years(self):
        """Test no SSD after holding 3+ years."""
        result = calculate_ssd(1_000_000, holding_years=3)
        assert result.ssd == 0.0
        assert result.ssd_rate == 0.0
        assert "3+ years" in result.note or "no SSD" in result.note.lower()


    def test_ssd_invalid_negative_years(self):
        """Test that negative holding years are rejected."""
        with pytest.raises(ValueError, match="cannot be negative"):
            calculate_ssd(1_000_000, holding_years=-1)
