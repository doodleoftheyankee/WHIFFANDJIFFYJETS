#!/usr/bin/env python3
"""
Programmatic API for running underwriting analyses.
Use this module to run analyses from scripts or integrate into other systems.

Usage:
    from analyze import run_full_analysis
    result = run_full_analysis(credit_score=700, monthly_income=8000, ...)
"""

from underwriting_engine import (
    BorrowerProfile, UnderwritingEngine,
    LoanPurpose, OccupancyType, PropertyType, IncomeDocType,
)
from deal_optimizer import DealOptimizer
from aus_strategy import AUSStrategyAnalyzer


def run_full_analysis(
    credit_score: int = 700,
    monthly_gross_income: float = 8000,
    monthly_debt_payments: float = 500,
    purchase_price: float = 400000,
    down_payment: float = 80000,
    loan_amount: float = 0,
    proposed_monthly_pitia: float = 2200,
    total_liquid_assets: float = 50000,
    retirement_assets: float = 0,
    credit_utilization_pct: float = 30,
    number_of_tradelines: int = 5,
    oldest_tradeline_months: int = 60,
    late_payments_12mo: int = 0,
    late_payments_24mo: int = 0,
    bankruptcy_months_ago: int = 999,
    foreclosure_months_ago: int = 999,
    collections_amount: float = 0,
    employment_months: int = 24,
    self_employed: bool = False,
    years_self_employed: int = 0,
    co_borrower_credit_score: int = 0,
    co_borrower_monthly_income: float = 0,
    loan_purpose: str = "purchase",
    occupancy: str = "primary_residence",
    property_type: str = "single_family",
    doc_type: str = "full_documentation",
    monthly_rental_income: float = 0,
) -> dict:
    """
    Run complete underwriting analysis and return structured results.

    Returns dict with keys:
        - underwriting: UnderwritingResult
        - optimization: dict with scenarios
        - strategy: dict with program comparison
        - summary: dict with key numbers
    """
    # Map string inputs to enums
    purpose_map = {
        "purchase": LoanPurpose.PURCHASE,
        "rate_term_refinance": LoanPurpose.RATE_TERM_REFI,
        "cash_out_refinance": LoanPurpose.CASH_OUT_REFI,
    }
    occ_map = {
        "primary_residence": OccupancyType.PRIMARY,
        "second_home": OccupancyType.SECOND_HOME,
        "investment_property": OccupancyType.INVESTMENT,
    }
    prop_map = {
        "single_family": PropertyType.SFR,
        "condo": PropertyType.CONDO,
        "townhome": PropertyType.TOWNHOME,
        "2_4_unit": PropertyType.MULTI_2_4,
        "manufactured": PropertyType.MANUFACTURED,
    }
    doc_map = {
        "full_documentation": IncomeDocType.FULL_DOC,
        "bank_statements": IncomeDocType.BANK_STATEMENTS,
        "asset_depletion": IncomeDocType.ASSET_DEPLETION,
        "dscr": IncomeDocType.DSCR,
    }

    borrower = BorrowerProfile(
        credit_score=credit_score,
        monthly_gross_income=monthly_gross_income,
        monthly_debt_payments=monthly_debt_payments,
        purchase_price=purchase_price,
        appraised_value=purchase_price,
        down_payment=down_payment,
        loan_amount=loan_amount,
        proposed_monthly_pitia=proposed_monthly_pitia,
        total_liquid_assets=total_liquid_assets,
        retirement_assets=retirement_assets,
        credit_utilization_pct=credit_utilization_pct,
        number_of_tradelines=number_of_tradelines,
        oldest_tradeline_months=oldest_tradeline_months,
        late_payments_12mo=late_payments_12mo,
        late_payments_24mo=late_payments_24mo,
        bankruptcy_months_ago=bankruptcy_months_ago,
        foreclosure_months_ago=foreclosure_months_ago,
        collections_amount=collections_amount,
        employment_months=employment_months,
        self_employed=self_employed,
        years_self_employed=years_self_employed,
        co_borrower_credit_score=co_borrower_credit_score if co_borrower_credit_score > 0 else None,
        co_borrower_monthly_income=co_borrower_monthly_income,
        loan_purpose=purpose_map.get(loan_purpose, LoanPurpose.PURCHASE),
        occupancy=occ_map.get(occupancy, OccupancyType.PRIMARY),
        property_type=prop_map.get(property_type, PropertyType.SFR),
        doc_type=doc_map.get(doc_type, IncomeDocType.FULL_DOC),
        monthly_rental_income=monthly_rental_income,
    )

    # Run all analyses
    engine = UnderwritingEngine()
    uw_result = engine.analyze(borrower)

    optimizer = DealOptimizer()
    opt_result = optimizer.optimize(borrower)

    analyzer = AUSStrategyAnalyzer()
    strategy_result = analyzer.analyze(borrower)

    # Build summary
    summary = {
        "recommendation": uw_result.recommendation.value,
        "score": uw_result.total_score,
        "max_score": uw_result.max_possible_score,
        "score_pct": uw_result.score_pct,
        "approval_probability": uw_result.approval_probability_pct,
        "front_end_dti": uw_result.front_end_dti,
        "back_end_dti": uw_result.back_end_dti,
        "ltv": uw_result.ltv,
        "estimated_llpa": uw_result.estimated_llpa,
        "compensating_factors": len(uw_result.compensating_factors),
        "risk_flags": len(uw_result.risk_flags),
        "risk_layers": strategy_result["risk_layers"].layer_count,
        "eligible_programs": len(strategy_result["eligible_programs"]),
        "best_program": strategy_result["eligible_programs"][0].platform.value if strategy_result["eligible_programs"] else "None",
    }

    return {
        "borrower": borrower,
        "underwriting": uw_result,
        "optimization": opt_result,
        "strategy": strategy_result,
        "summary": summary,
    }


def print_summary(result: dict):
    """Print a concise text summary of the analysis."""
    s = result["summary"]
    uw = result["underwriting"]

    print(f"\n{'='*60}")
    print(f"  UNDERWRITING ANALYSIS SUMMARY")
    print(f"{'='*60}")
    print(f"  Recommendation:     {s['recommendation']}")
    print(f"  Score:              {s['score']}/{s['max_score']} ({s['score_pct']}%)")
    print(f"  Approval Prob:      {s['approval_probability']}%")
    print(f"  Back-End DTI:       {s['back_end_dti']}%")
    print(f"  LTV:                {s['ltv']}%")
    print(f"  LLPA:               {s['estimated_llpa']:+.3f}%")
    print(f"  Risk Layers:        {s['risk_layers']}")
    print(f"  Comp Factors:       {s['compensating_factors']}")
    print(f"  Best Program:       {s['best_program']}")
    print(f"  Eligible Programs:  {s['eligible_programs']}")

    print(f"\n  Key Actions:")
    actions = []
    for factor in uw.factors:
        for action in factor.action_items:
            actions.append(action)
    for i, action in enumerate(actions[:5], 1):
        print(f"    {i}. {action}")

    print(f"\n  Deal Structure Notes (first 10):")
    for note in uw.deal_structure_notes[:10]:
        print(f"    {note}")
    print()


# Quick test
if __name__ == "__main__":
    # Example: Borrower with 685 FICO, high utilization, moderate DTI
    result = run_full_analysis(
        credit_score=685,
        monthly_gross_income=7500,
        monthly_debt_payments=800,
        purchase_price=425000,
        down_payment=42500,
        proposed_monthly_pitia=2650,
        total_liquid_assets=65000,
        retirement_assets=25000,
        credit_utilization_pct=42,
        number_of_tradelines=6,
        oldest_tradeline_months=72,
        late_payments_24mo=1,
        employment_months=36,
    )
    print_summary(result)
