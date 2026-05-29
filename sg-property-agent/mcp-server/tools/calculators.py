"""Deterministic financial calculators for Singapore property purchases.

Rate tables as of 2023/2024 — update when government changes rates.
These functions are registered as MCP tools in server.py.
"""


def calculate_bsd(price: float) -> dict:
    """Buyer's Stamp Duty — progressive rate table (as of 2023)."""
    brackets = [
        (180_000,       0.01),
        (180_000,       0.02),
        (640_000,       0.03),
        (500_000,       0.04),
        (1_500_000,     0.05),
        (float("inf"), 0.06),
    ]
    remaining = price
    total = 0.0
    breakdown_parts = []
    for limit, rate in brackets:
        taxable = min(remaining, limit)
        amount = taxable * rate
        total += amount
        breakdown_parts.append(f"{rate*100:.0f}% × ${taxable:,.0f} = ${amount:,.0f}")
        remaining -= taxable
        if remaining <= 0:
            break
    return {
        "amount": round(total),
        "breakdown": " + ".join(breakdown_parts),
        "source": "IRAS",
    }


def calculate_absd(price: float, citizenship: str, property_count: int) -> dict:
    """
    Additional Buyer's Stamp Duty — 2023 rates (post April 2023 hike).
    property_count: number of residential properties owned AFTER this purchase.
    citizenship: one of singapore_citizen | singapore_pr | foreigner | company
    """
    rates = {
        ("singapore_citizen",  1): 0.00,
        ("singapore_citizen",  2): 0.20,
        ("singapore_citizen",  3): 0.30,
        ("singapore_pr",       1): 0.05,
        ("singapore_pr",       2): 0.30,
        ("singapore_pr",       3): 0.35,
        ("foreigner",          1): 0.60,
        ("foreigner",          2): 0.60,
        ("foreigner",          3): 0.60,
        ("company",            1): 0.65,
        ("company",            2): 0.65,
        ("company",            3): 0.65,
    }
    count_key = min(property_count, 3)
    rate = rates.get((citizenship, count_key), 0.60)
    amount = round(price * rate)
    return {
        "rate": rate,
        "rate_pct": f"{rate*100:.0f}%",
        "amount": amount,
        "citizenship": citizenship,
        "property_count": property_count,
        "note": "Post April 2023 rates. ABSD remission may apply for married couples (SC+SC, SC+PR).",
        "source": "IRAS",
    }


def calculate_tdsr(monthly_income: float, total_monthly_debt: float) -> dict:
    """Total Debt Servicing Ratio — MAS threshold is 55%."""
    threshold = 0.55
    max_total_debt = monthly_income * threshold
    max_new_loan_payment = max(0, max_total_debt - total_monthly_debt)
    ratio = total_monthly_debt / monthly_income if monthly_income > 0 else 1.0
    ok = ratio <= threshold
    return {
        "ok": ok,
        "ratio": round(ratio, 4),
        "ratio_pct": f"{ratio*100:.1f}%",
        "threshold_pct": "55%",
        "max_monthly_loan_payment": round(max_new_loan_payment),
        "monthly_income": monthly_income,
        "existing_monthly_debt": total_monthly_debt,
        "source": "MAS",
    }


def calculate_msr(monthly_income: float, proposed_monthly_hdb_loan: float) -> dict:
    """
    Mortgage Servicing Ratio — 30% threshold.
    Applies to HDB loans and bank loans for HDB flats and ECs within MOP.
    """
    threshold = 0.30
    max_payment = monthly_income * threshold
    ok = proposed_monthly_hdb_loan <= max_payment
    ratio = proposed_monthly_hdb_loan / monthly_income if monthly_income > 0 else 1.0
    return {
        "ok": ok,
        "ratio": round(ratio, 4),
        "ratio_pct": f"{ratio*100:.1f}%",
        "threshold_pct": "30%",
        "max_monthly_payment": round(max_payment),
        "proposed_payment": proposed_monthly_hdb_loan,
        "note": "MSR applies to HDB flats and ECs within MOP only.",
        "source": "MAS",
    }


def calculate_ltv(loan_type: str, property_count: int) -> dict:
    """
    Loan-to-Value limits.
    loan_type: 'hdb' | 'bank'
    property_count: number of outstanding mortgages at time of purchase.
    """
    ltv_table = {
        ("hdb",  0): (0.80, "HDB loan: up to 80% for first property with no outstanding loans"),
        ("hdb",  1): (0.55, "HDB loan: up to 55% if one outstanding mortgage"),
        ("hdb",  2): (0.35, "HDB loan: up to 35% if two+ outstanding mortgages"),
        ("bank", 0): (0.75, "Bank loan: up to 75% for first property"),
        ("bank", 1): (0.45, "Bank loan: up to 45% if one outstanding mortgage"),
        ("bank", 2): (0.35, "Bank loan: up to 35% if two+ outstanding mortgages"),
    }
    count_key = min(property_count, 2)
    max_ltv, note = ltv_table.get((loan_type, count_key), (0.75, "Default bank LTV"))
    return {
        "loan_type": loan_type,
        "max_ltv": max_ltv,
        "max_ltv_pct": f"{max_ltv*100:.0f}%",
        "outstanding_mortgages": property_count,
        "note": note,
        "source": "MAS",
    }


def calculate_cpf_withdrawal(
    cpf_oa_balance: float,
    property_price: float,
    remaining_lease_years: int,
) -> dict:
    """
    CPF OA withdrawal limit for property purchase.
    If remaining_lease < 30 years: CPF usage not allowed.
    If 30–59 years: prorated limit applies.
    If 60+ years: up to property price (within OA balance).
    """
    if remaining_lease_years < 30:
        return {
            "usable": 0,
            "note": "CPF cannot be used: remaining lease < 30 years.",
            "source": "CPF Board",
        }

    if remaining_lease_years >= 60:
        usable = min(cpf_oa_balance, property_price)
        return {
            "usable": round(usable),
            "note": "Full OA balance may be used (lease >= 60 years).",
            "source": "CPF Board",
        }

    ratio = remaining_lease_years / 60
    usable = min(cpf_oa_balance, property_price * ratio)
    return {
        "usable": round(usable),
        "note": f"Prorated CPF usage: {remaining_lease_years} yr lease / 60 = {ratio:.0%} of price.",
        "source": "CPF Board",
    }


def calculate_hdb_grants(
    citizenship: str,
    monthly_income: float,
    flat_type: str,
    proximity_to_parents: bool,
) -> dict:
    """
    HDB grant eligibility — EHG, PHG, Family Grant (resale only).
    flat_type: '2room' | '3room' | '4room' | '5room' | 'executive'
    proximity_to_parents: True if living with parents / within 4km
    """
    grants = []

    # Enhanced CPF Housing Grant (EHG) — BTO and resale, income-based
    if citizenship == "singapore_citizen" and monthly_income <= 9000:
        ehg_table = [
            (1500, 80_000), (2000, 75_000), (2500, 70_000), (3000, 65_000),
            (3500, 60_000), (4000, 55_000), (4500, 50_000), (5000, 45_000),
            (5500, 40_000), (6000, 35_000), (6500, 30_000), (7000, 25_000),
            (7500, 20_000), (8000, 15_000), (8500, 10_000), (9000,  5_000),
        ]
        ehg = next((amt for ceil, amt in ehg_table if monthly_income <= ceil), 0)
        if ehg:
            grants.append({"name": "EHG", "amount": ehg, "note": "Enhanced CPF Housing Grant"})

    # Proximity Housing Grant (PHG) — resale only
    if flat_type not in ("2room",):
        phg = 30_000 if proximity_to_parents else 20_000
        grants.append({
            "name": "PHG",
            "amount": phg,
            "note": f"Proximity Housing Grant ({'living with parents' if proximity_to_parents else 'within 4km of parents'})",
        })

    # Family Grant (formerly AHG) — resale, SC first-timers
    if citizenship == "singapore_citizen" and monthly_income <= 14_000:
        fg = 50_000 if flat_type in ("2room", "3room", "4room") else 40_000
        grants.append({"name": "Family Grant", "amount": fg, "note": "For SC first-timer families buying resale"})

    total = sum(g["amount"] for g in grants)
    return {
        "applicable": len(grants) > 0,
        "grants": grants,
        "total_grants": total,
        "note": "Grant amounts are estimates. Eligibility subject to HDB assessment.",
        "source": "HDB",
    }
