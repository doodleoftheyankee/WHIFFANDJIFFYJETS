#!/usr/bin/env python3
"""
Automated Underwriting System — Interactive CLI
================================================
Run: python3 main.py

Provides full underwriting analysis with:
  - AUS score breakdown (mirrors DU/LP scoring)
  - Deal structure optimization
  - Program eligibility comparison (DU, LP, FHA, VA)
  - Risk layering analysis
  - Step-by-step action plan for approval
"""

import sys
from underwriting_engine import (
    BorrowerProfile, UnderwritingEngine, AUSRecommendation,
    LoanPurpose, OccupancyType, PropertyType, IncomeDocType, RiskLevel,
)
from deal_optimizer import DealOptimizer
from aus_strategy import AUSStrategyAnalyzer


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
WHITE = "\033[97m"
BG_GREEN = "\033[42m"
BG_RED = "\033[41m"
BG_YELLOW = "\033[43m"


def color_risk(risk_level):
    if risk_level == RiskLevel.LOW:
        return f"{GREEN}{risk_level.value}{RESET}"
    elif risk_level == RiskLevel.MODERATE:
        return f"{YELLOW}{risk_level.value}{RESET}"
    elif risk_level == RiskLevel.HIGH:
        return f"{RED}{risk_level.value}{RESET}"
    else:
        return f"{RED}{BOLD}{risk_level.value}{RESET}"


def color_recommendation(rec):
    if rec == AUSRecommendation.APPROVE_ELIGIBLE:
        return f"{BG_GREEN}{WHITE}{BOLD} {rec.value} {RESET}"
    elif rec == AUSRecommendation.APPROVE_INELIGIBLE:
        return f"{GREEN}{rec.value}{RESET}"
    elif rec == AUSRecommendation.REFER_ELIGIBLE:
        return f"{YELLOW}{rec.value}{RESET}"
    elif rec == AUSRecommendation.REFER_INELIGIBLE:
        return f"{RED}{rec.value}{RESET}"
    else:
        return f"{RED}{BOLD}{rec.value}{RESET}"


def color_pct(value, good_threshold=70, warn_threshold=50):
    if value >= good_threshold:
        return f"{GREEN}{value:.1f}%{RESET}"
    elif value >= warn_threshold:
        return f"{YELLOW}{value:.1f}%{RESET}"
    else:
        return f"{RED}{value:.1f}%{RESET}"


def bar(value, max_val, width=30):
    filled = int((value / max_val) * width) if max_val > 0 else 0
    filled = min(filled, width)
    empty = width - filled
    if filled / width >= 0.7:
        color = GREEN
    elif filled / width >= 0.5:
        color = YELLOW
    else:
        color = RED
    return f"{color}{'█' * filled}{RESET}{'░' * empty}"


def header(text, char="="):
    line = char * 64
    print(f"\n{BOLD}{CYAN}{line}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{line}{RESET}")


def subheader(text):
    print(f"\n  {BOLD}{BLUE}--- {text} ---{RESET}")


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def get_float(prompt, default=0.0):
    try:
        val = input(f"  {prompt} [{default}]: ").strip()
        return float(val) if val else default
    except ValueError:
        print(f"    {YELLOW}Invalid number, using {default}{RESET}")
        return default


def get_int(prompt, default=0):
    try:
        val = input(f"  {prompt} [{default}]: ").strip()
        return int(val) if val else default
    except ValueError:
        print(f"    {YELLOW}Invalid number, using {default}{RESET}")
        return default


def get_bool(prompt, default=False):
    val = input(f"  {prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    if not val:
        return default
    return val in ('y', 'yes', '1', 'true')


def get_choice(prompt, choices, default=0):
    print(f"  {prompt}")
    for i, (label, _) in enumerate(choices):
        marker = " *" if i == default else ""
        print(f"    {i + 1}. {label}{marker}")
    try:
        val = input(f"  Choice [{default + 1}]: ").strip()
        idx = (int(val) - 1) if val else default
        return choices[idx][1]
    except (ValueError, IndexError):
        return choices[default][1]


# ---------------------------------------------------------------------------
# Input collection
# ---------------------------------------------------------------------------

def collect_borrower_data() -> BorrowerProfile:
    """Interactive data collection."""
    header("BORROWER & DEAL INFORMATION")

    subheader("Borrower Credit")
    credit_score = get_int("Credit score (FICO)", 700)
    co_score = get_int("Co-borrower credit score (0 if none)", 0)
    co_score = co_score if co_score > 0 else None
    utilization = get_float("Credit card utilization %", 30)
    num_tradelines = get_int("Number of tradelines", 5)
    oldest_tradeline = get_int("Oldest tradeline (months)", 60)
    lates_12 = get_int("Late payments in last 12 months", 0)
    lates_24 = get_int("Late payments in last 24 months", 0)
    bk_months = get_int("Months since bankruptcy (999 if never)", 999)
    fc_months = get_int("Months since foreclosure (999 if never)", 999)
    collections = get_float("Outstanding collections amount $", 0)

    subheader("Income & Employment")
    monthly_income = get_float("Monthly gross income $", 8000)
    co_income = get_float("Co-borrower monthly income $ (0 if none)", 0)
    self_employed = get_bool("Self-employed?", False)
    if self_employed:
        years_se = get_int("Years self-employed", 2)
        emp_months = years_se * 12
    else:
        years_se = 0
        emp_months = get_int("Months at current employer", 24)

    subheader("Monthly Debts (minimum payments)")
    monthly_debts = get_float("Total monthly debt payments (cards, auto, student, etc) $", 500)

    subheader("Property & Deal")
    loan_purpose = get_choice("Loan purpose:", [
        ("Purchase", LoanPurpose.PURCHASE),
        ("Rate/Term Refinance", LoanPurpose.RATE_TERM_REFI),
        ("Cash-Out Refinance", LoanPurpose.CASH_OUT_REFI),
    ], 0)

    occupancy = get_choice("Occupancy:", [
        ("Primary Residence", OccupancyType.PRIMARY),
        ("Second Home", OccupancyType.SECOND_HOME),
        ("Investment Property", OccupancyType.INVESTMENT),
    ], 0)

    prop_type = get_choice("Property type:", [
        ("Single Family", PropertyType.SFR),
        ("Condo", PropertyType.CONDO),
        ("Townhome", PropertyType.TOWNHOME),
        ("2-4 Unit", PropertyType.MULTI_2_4),
        ("Manufactured", PropertyType.MANUFACTURED),
    ], 0)

    purchase_price = get_float("Purchase price / current value $", 400000)
    appraised_value = get_float("Appraised value $ (0 = same as price)", 0)
    down_payment = get_float("Down payment $", 80000)
    loan_amount = get_float("Loan amount $ (0 = auto-calculate)", 0)

    subheader("Proposed Payment")
    pitia = get_float("Proposed monthly PITIA (P+I+Tax+Insurance+HOA) $", 2200)

    subheader("Assets & Reserves")
    liquid_assets = get_float("Total liquid assets (checking, savings, stocks) $", 50000)
    retirement = get_float("Retirement assets (401k, IRA) $", 0)

    subheader("Documentation")
    doc_type = get_choice("Income documentation type:", [
        ("Full Documentation (W-2, Tax Returns)", IncomeDocType.FULL_DOC),
        ("Bank Statements (Self-Employed)", IncomeDocType.BANK_STATEMENTS),
        ("Asset Depletion", IncomeDocType.ASSET_DEPLETION),
        ("DSCR (Investment Property)", IncomeDocType.DSCR),
    ], 0)

    rental_income = 0.0
    if occupancy == OccupancyType.INVESTMENT:
        rental_income = get_float("Monthly rental income $", 0)

    return BorrowerProfile(
        credit_score=credit_score,
        monthly_gross_income=monthly_income,
        co_borrower_credit_score=co_score,
        co_borrower_monthly_income=co_income,
        monthly_debt_payments=monthly_debts,
        purchase_price=purchase_price,
        appraised_value=appraised_value if appraised_value > 0 else purchase_price,
        loan_amount=loan_amount,
        down_payment=down_payment,
        loan_purpose=loan_purpose,
        occupancy=occupancy,
        property_type=prop_type,
        proposed_monthly_pitia=pitia,
        total_liquid_assets=liquid_assets,
        retirement_assets=retirement,
        self_employed=self_employed,
        years_self_employed=years_se,
        employment_months=emp_months,
        late_payments_12mo=lates_12,
        late_payments_24mo=lates_24,
        bankruptcy_months_ago=bk_months,
        foreclosure_months_ago=fc_months,
        collections_amount=collections,
        number_of_tradelines=num_tradelines,
        oldest_tradeline_months=oldest_tradeline,
        credit_utilization_pct=utilization,
        doc_type=doc_type,
        monthly_rental_income=rental_income,
    )


# ---------------------------------------------------------------------------
# Display results
# ---------------------------------------------------------------------------

def display_underwriting_result(result):
    header("AUS SCORING ANALYSIS")

    # Top-level summary
    print(f"\n  {BOLD}AUS Recommendation:{RESET}  {color_recommendation(result.recommendation)}")
    print(f"  {BOLD}Overall Score:{RESET}        {result.total_score} / {result.max_possible_score}  ({color_pct(result.score_pct)})")
    print(f"  {BOLD}Approval Probability:{RESET} {color_pct(result.approval_probability_pct)}")
    print()
    print(f"  {BOLD}Front-End DTI:{RESET}  {result.front_end_dti:.1f}%")
    print(f"  {BOLD}Back-End DTI:{RESET}   {result.back_end_dti:.1f}%")
    print(f"  {BOLD}LTV:{RESET}            {result.ltv:.1f}%")
    print(f"  {BOLD}Est. LLPA:{RESET}      {result.estimated_llpa:+.3f}%")

    # Factor breakdown
    subheader("SCORING BREAKDOWN")
    for factor in result.factors:
        pct = (factor.points / factor.max_points * 100) if factor.max_points > 0 else 0
        print(f"\n  {BOLD}{factor.category} > {factor.name}{RESET}")
        print(f"  Value:  {factor.value}")
        print(f"  Score:  {bar(factor.points, factor.max_points)} {factor.points:.0f}/{factor.max_points:.0f} ({pct:.0f}%)")
        print(f"  Risk:   {color_risk(factor.risk_level)}")
        if factor.action_items:
            print(f"  {YELLOW}Actions:{RESET}")
            for action in factor.action_items:
                print(f"    -> {action}")

    # Compensating factors
    if result.compensating_factors:
        subheader("COMPENSATING FACTORS (Working in Your Favor)")
        for cf in result.compensating_factors:
            print(f"  {GREEN}+{RESET} {cf}")

    # Risk flags
    if result.risk_flags:
        subheader("RISK FLAGS (Must Address)")
        for rf in result.risk_flags:
            print(f"  {RED}!{RESET} {rf}")


def display_deal_structure(result):
    subheader("DEAL STRUCTURE RECOMMENDATIONS")
    for note in result.deal_structure_notes:
        print(f"  {note}")


def display_optimization(opt_result):
    header("DEAL OPTIMIZATION SCENARIOS")

    baseline = opt_result["baseline"]
    print(f"\n  {BOLD}Current State:{RESET}")
    print(f"  Recommendation: {color_recommendation(baseline.recommendation)}")
    print(f"  Score: {baseline.score_pct:.1f}%  |  Approval Prob: {baseline.approval_probability_pct:.1f}%")

    # Approval path
    path = opt_result.get("approval_path", [])
    if path:
        subheader("PATH TO APPROVE/ELIGIBLE")
        for item in path:
            if "message" in item:
                print(f"  {item['message']}")
            else:
                print(f"  {BOLD}{GREEN}{item['strategy']}{RESET}")
                print(f"    Scenario: {item['scenario']}")
                print(f"    Cost: ${item['cost']:,.0f}")
                print(f"    Timeframe: {item['timeframe']}")
                print(f"    {item['description']}")

    # Quick wins
    quick = opt_result.get("quick_wins", [])
    if quick:
        subheader("QUICK WINS (Immediate - 2 Weeks)")
        for s in quick:
            _display_scenario(s, baseline)

    # Medium term
    medium = opt_result.get("medium_term", [])
    if medium:
        subheader("MEDIUM TERM (1-3 Months)")
        for s in medium:
            _display_scenario(s, baseline)

    # Long term
    long_term = opt_result.get("long_term", [])
    if long_term:
        subheader("LONG TERM (3-12 Months)")
        for s in long_term[:3]:
            _display_scenario(s, baseline)


def _display_scenario(scenario, baseline):
    prob_delta = scenario.approval_prob_improvement
    score_delta = scenario.score_improvement
    prob_color = GREEN if prob_delta > 0 else RED
    rec_str = color_recommendation(scenario.new_recommendation) if scenario.new_recommendation else "N/A"

    print(f"\n  {BOLD}{scenario.name}{RESET}")
    print(f"    {scenario.description}")
    print(f"    Difficulty: {scenario.difficulty}  |  Timeframe: {scenario.timeframe}  |  Cost: ${scenario.estimated_cost:,.0f}")
    print(f"    Impact: Score {score_delta:+.1f}%  |  Approval Prob {prob_color}{prob_delta:+.1f}%{RESET}  |  Rec: {rec_str}")


def display_aus_strategy(strategy_result):
    header("AUS PROGRAM COMPARISON & STRATEGY")

    # Program comparison
    programs = strategy_result["programs"]
    eligible = strategy_result["eligible_programs"]

    subheader("PROGRAM ELIGIBILITY")
    for prog in programs:
        status = f"{GREEN}ELIGIBLE{RESET}" if prog.eligible else f"{RED}INELIGIBLE{RESET}"
        rank = f" {BOLD}[#{prog.priority_rank} RECOMMENDED]{RESET}" if prog.priority_rank > 0 else ""
        print(f"\n  {BOLD}{prog.platform.value}{RESET} — {status}{rank}")
        print(f"    Confidence: {prog.confidence}")
        print(f"    Max DTI: {prog.max_dti_allowed}%  |  Max LTV: {prog.max_ltv_allowed}%  |  Min FICO: {prog.min_credit_score}")
        if prog.estimated_rate_adjustment != 0:
            print(f"    Rate adjustment: {prog.estimated_rate_adjustment:+.3f}%")
        if prog.key_advantages:
            print(f"    {GREEN}Advantages:{RESET}")
            for adv in prog.key_advantages[:3]:
                print(f"      + {adv}")
        if prog.key_risks:
            print(f"    {RED}Risks:{RESET}")
            for risk in prog.key_risks[:3]:
                print(f"      ! {risk}")

    # Risk layering
    risk = strategy_result["risk_layers"]
    subheader(f"RISK LAYERING ANALYSIS ({risk.layer_count} layers)")
    print(f"  {risk.assessment}")
    if risk.layers:
        for layer in risk.layers:
            print(f"  {RED}-{RESET} {layer}")
    print(f"  {BOLD}Recommendation:{RESET} {risk.recommendation}")

    # Submission strategy
    strategy = strategy_result["submission_strategy"]
    print()
    for line in strategy:
        print(f"  {line}")


def display_guideline_reference(guidelines):
    header("GUIDELINE QUICK REFERENCE")
    for program, rules in guidelines.items():
        subheader(program.upper())
        for key, value in rules.items():
            label = key.replace("_", " ").title()
            print(f"    {label}: {value}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def print_banner():
    print(f"""
{BOLD}{CYAN}
 ╔══════════════════════════════════════════════════════════════╗
 ║          AUTOMATED UNDERWRITING SCORING SYSTEM              ║
 ║                                                              ║
 ║   AUS Analysis  •  Deal Optimizer  •  Program Strategy       ║
 ╚══════════════════════════════════════════════════════════════╝
{RESET}
  This system analyzes loan applications the same way DU/LP
  score them, then shows you exactly how to structure the deal
  for maximum approval probability.

  Scoring based on the 4 C's: Credit, Capacity, Collateral, Capital
""")


def run_demo():
    """Run with a sample borrower for demonstration."""
    print(f"\n{BOLD}{YELLOW}  Running DEMO with sample borrower...{RESET}\n")
    borrower = BorrowerProfile(
        credit_score=685,
        monthly_gross_income=7500,
        co_borrower_credit_score=None,
        co_borrower_monthly_income=0,
        monthly_debt_payments=800,
        purchase_price=425000,
        appraised_value=425000,
        down_payment=42500,
        loan_amount=382500,
        loan_purpose=LoanPurpose.PURCHASE,
        occupancy=OccupancyType.PRIMARY,
        property_type=PropertyType.SFR,
        proposed_monthly_pitia=2650,
        total_liquid_assets=65000,
        retirement_assets=25000,
        self_employed=False,
        employment_months=36,
        late_payments_12mo=0,
        late_payments_24mo=1,
        bankruptcy_months_ago=999,
        foreclosure_months_ago=999,
        collections_amount=0,
        number_of_tradelines=6,
        oldest_tradeline_months=72,
        credit_utilization_pct=42,
        doc_type=IncomeDocType.FULL_DOC,
    )
    return borrower


def main():
    print_banner()

    # Mode selection
    mode = input(f"  {BOLD}Enter mode:{RESET} [1] Interactive  [2] Demo  [3] Quick (score only): ").strip()

    if mode == "2":
        borrower = run_demo()
    elif mode == "3":
        borrower = run_demo()  # quick mode uses demo data
    else:
        borrower = collect_borrower_data()

    # Run analysis
    print(f"\n{BOLD}{CYAN}  Analyzing...{RESET}\n")

    # 1. Core underwriting
    engine = UnderwritingEngine()
    uw_result = engine.analyze(borrower)
    display_underwriting_result(uw_result)
    display_deal_structure(uw_result)

    if mode == "3":
        # Quick mode — stop here
        print(f"\n{BOLD}  Quick analysis complete. Run in full mode for optimization & strategy.{RESET}\n")
        return

    # 2. Deal optimization
    optimizer = DealOptimizer()
    opt_result = optimizer.optimize(borrower)
    display_optimization(opt_result)

    # 3. AUS strategy
    analyzer = AUSStrategyAnalyzer()
    strategy_result = analyzer.analyze(borrower)
    display_aus_strategy(strategy_result)
    display_guideline_reference(strategy_result["guideline_reference"])

    # Final summary
    header("FINAL ACTION PLAN")
    print(f"""
  {BOLD}Current Status:{RESET} {color_recommendation(uw_result.recommendation)}
  {BOLD}Score:{RESET}          {uw_result.total_score}/{uw_result.max_possible_score} ({color_pct(uw_result.score_pct)})
  {BOLD}Approval Prob:{RESET}  {color_pct(uw_result.approval_probability_pct)}

  {BOLD}Key Metrics:{RESET}
    DTI:  {uw_result.back_end_dti:.1f}%  |  LTV: {uw_result.ltv:.1f}%  |  FICO: {borrower.credit_score}

  {BOLD}Top 3 Actions to Take:{RESET}""")

    all_actions = []
    for factor in uw_result.factors:
        for action in factor.action_items:
            all_actions.append(action)

    for i, action in enumerate(all_actions[:5], 1):
        print(f"    {i}. {action}")

    if opt_result.get("best_scenario"):
        best = opt_result["best_scenario"]
        print(f"""
  {BOLD}Best Optimization Move:{RESET}
    {best.name} ({best.timeframe}, ${best.estimated_cost:,.0f})
    -> Approval probability: {best.result.approval_probability_pct:+.1f}% (from {uw_result.approval_probability_pct:.1f}%)
""")

    print(f"\n  {BOLD}{CYAN}Analysis complete. Structure the deal, re-run, and iterate until Approve/Eligible.{RESET}\n")


if __name__ == "__main__":
    main()
