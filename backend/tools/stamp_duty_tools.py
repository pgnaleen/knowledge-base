from langchain_core.tools import tool
from tools.stamp_duty import BuyerProfile, PropertyType
from tools.stamp_duty import calculate_stamp_duty as _calc_stamp_duty
from tools.stamp_duty import calculate_ssd as _calc_ssd


@tool
def calculate_stamp_duty(
    purchase_price: float,
    buyer_profile: str,
    property_type: str = "residential",
) -> str:
    """Calculate Buyer's Stamp Duty (BSD) and Additional Buyer's Stamp Duty (ABSD) for a Singapore property purchase.
    buyer_profile options: sc_first, sc_second, sc_third_plus, pr_first, pr_second_plus, foreigner, company
    property_type options: residential, non_residential
    Returns exact BSD, ABSD amounts, total duty, and effective rate in SGD."""
    try:
        profile = BuyerProfile(buyer_profile)
        prop_type = PropertyType(property_type)
        result = _calc_stamp_duty(
            price=purchase_price,
            buyer_profile=profile,
            property_type=prop_type,
        )
        return (
            f"BSD: SGD {result.bsd:,.2f}\n"
            f"ABSD: SGD {result.absd:,.2f} ({result.absd_rate * 100:.0f}%)\n"
            f"Total Stamp Duty: SGD {result.total:,.2f}\n"
            f"Effective Rate: {result.effective_rate * 100:.2f}%"
        )
    except ValueError as exc:
        return (
            f"Invalid input: {exc}. "
            "Valid buyer_profile values: sc_first, sc_second, sc_third_plus, "
            "pr_first, pr_second_plus, foreigner, company"
        )


@tool
def calculate_ssd(sale_price: float, holding_years: int) -> str:
    """Calculate Seller's Stamp Duty (SSD) for a Singapore residential property sale.
    holding_years: number of full years the property was held before selling (use 0 for less than 1 year).
    SSD applies only within the first 3 years: Year 1 = 12%, Year 2 = 8%, Year 3 = 4%, after = 0%.
    Returns exact SSD amount and applicable rate."""
    try:
        result = _calc_ssd(sale_price=sale_price, holding_years=holding_years)
        return (
            f"SSD: SGD {result.ssd:,.2f} ({result.ssd_rate * 100:.0f}%)\n"
            f"Note: {result.note}"
        )
    except ValueError as exc:
        return f"Invalid input: {exc}"
