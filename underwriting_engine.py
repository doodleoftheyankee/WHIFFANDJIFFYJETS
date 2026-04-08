"""
Automated Underwriting Scoring Engine
======================================
Core engine that mirrors how AUS platforms (Desktop Underwriter / Loan Product Advisor)
evaluate and score loan applications. Provides transparent scoring breakdowns and
identifies exactly which factors are helping or hurting approval odds.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums & Constants
# ---------------------------------------------------------------------------

class LoanPurpose(Enum):
    PURCHASE = "purchase"
    RATE_TERM_REFI = "rate_term_refinance"
    CASH_OUT_REFI = "cash_out_refinance"


class OccupancyType(Enum):
    PRIMARY = "primary_residence"
    SECOND_HOME = "second_home"
    INVESTMENT = "investment_property"


class PropertyType(Enum):
    SFR = "single_family"
    CONDO = "condo"
    TOWNHOME = "townhome"
    MULTI_2_4 = "2_4_unit"
    MANUFACTURED = "manufactured"


class IncomeDocType(Enum):
    FULL_DOC = "full_documentation"
    BANK_STATEMENTS = "bank_statements"
    ASSET_DEPLETION = "asset_depletion"
    DSCR = "dscr"  # debt-service coverage ratio (investment)


class AUSRecommendation(Enum):
    APPROVE_ELIGIBLE = "Approve/Eligible"
    APPROVE_INELIGIBLE = "Approve/Ineligible"
    REFER_ELIGIBLE = "Refer with Caution/Eligible"
    REFER_INELIGIBLE = "Refer with Caution/Ineligible"
    OUT_OF_SCOPE = "Out of Scope"


class RiskLevel(Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    VERY_HIGH = "VERY HIGH"


# AUS guideline thresholds
DTI_THRESHOLDS = {
    "agency_standard": 43.0,
    "agency_max_strong": 50.0,  # with strong compensating factors
    "fha_standard": 43.0,
    "fha_max": 57.0,  # with compensating factors
    "va_no_limit": 41.0,  # VA has no hard cap but 41% triggers manual review
    "non_qm_max": 55.0,
}

LTV_LIMITS = {
    # (loan_purpose, occupancy) -> max LTV
    ("purchase", "primary"): 97.0,
    ("purchase", "second_home"): 90.0,
    ("purchase", "investment"): 85.0,
    ("rate_term_refi", "primary"): 97.0,
    ("rate_term_refi", "second_home"): 90.0,
    ("rate_term_refi", "investment"): 85.0,
    ("cash_out_refi", "primary"): 80.0,
    ("cash_out_refi", "second_home"): 75.0,
    ("cash_out_refi", "investment"): 75.0,
}

CREDIT_TIER_MAP = {
    (780, 850): {"label": "Excellent", "llpa_adj": -0.25, "weight": 1.0},
    (740, 779): {"label": "Very Good", "llpa_adj": 0.0, "weight": 0.95},
    (700, 739): {"label": "Good", "llpa_adj": 0.50, "weight": 0.85},
    (680, 699): {"label": "Fair+", "llpa_adj": 1.00, "weight": 0.75},
    (660, 679): {"label": "Fair", "llpa_adj": 1.75, "weight": 0.65},
    (640, 659): {"label": "Below Avg", "llpa_adj": 2.50, "weight": 0.55},
    (620, 639): {"label": "Minimum Conv", "llpa_adj": 3.25, "weight": 0.45},
    (580, 619): {"label": "FHA Territory", "llpa_adj": 4.00, "weight": 0.35},
    (500, 579): {"label": "Sub-prime", "llpa_adj": 5.00, "weight": 0.20},
    (300, 499): {"label": "Deep Sub-prime", "llpa_adj": 7.00, "weight": 0.05},
}

# Months of reserves scoring
RESERVES_SCORING = {
    (0, 0): {"points": 0, "label": "No reserves"},
    (1, 2): {"points": 5, "label": "Minimal reserves"},
    (3, 5): {"points": 15, "label": "Adequate reserves"},
    (6, 11): {"points": 30, "label": "Strong reserves"},
    (12, 23): {"points": 45, "label": "Very strong reserves"},
    (24, 999): {"points": 60, "label": "Exceptional reserves"},
}


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class BorrowerProfile:
    """All borrower & deal data needed for underwriting."""
    # Borrower info
    credit_score: int
    monthly_gross_income: float
    annual_gross_income: float = 0.0  # auto-calculated if zero
    employment_months: int = 24  # months at current job
    self_employed: bool = False
    years_self_employed: int = 0

    # Co-borrower (optional)
    co_borrower_credit_score: Optional[int] = None
    co_borrower_monthly_income: float = 0.0

    # Existing debts (monthly payments)
    monthly_debt_payments: float = 0.0  # all minimum payments (cards, auto, student, etc)
    monthly_housing_payment: float = 0.0  # current rent/mortgage

    # Property / Deal
    purchase_price: float = 0.0
    appraised_value: float = 0.0
    loan_amount: float = 0.0
    down_payment: float = 0.0
    loan_purpose: LoanPurpose = LoanPurpose.PURCHASE
    occupancy: OccupancyType = OccupancyType.PRIMARY
    property_type: PropertyType = PropertyType.SFR

    # Proposed PITIA (principal, interest, taxes, insurance, association)
    proposed_monthly_pitia: float = 0.0

    # Assets & Reserves
    total_liquid_assets: float = 0.0
    retirement_assets: float = 0.0  # counted at 60-70%
    months_reserves: float = 0.0  # auto-calculated if zero

    # Credit history details
    late_payments_12mo: int = 0
    late_payments_24mo: int = 0
    bankruptcy_months_ago: int = 999  # set to 999 if never
    foreclosure_months_ago: int = 999
    collections_amount: float = 0.0
    number_of_tradelines: int = 0
    oldest_tradeline_months: int = 0
    credit_utilization_pct: float = 0.0

    # Income documentation
    doc_type: IncomeDocType = IncomeDocType.FULL_DOC

    # Rental income (investment properties)
    monthly_rental_income: float = 0.0

    def __post_init__(self):
        if self.annual_gross_income == 0.0:
            self.annual_gross_income = self.monthly_gross_income * 12
        if self.appraised_value == 0.0 and self.purchase_price > 0:
            self.appraised_value = self.purchase_price
        if self.down_payment == 0.0 and self.purchase_price > 0 and self.loan_amount > 0:
            self.down_payment = self.purchase_price - self.loan_amount
        if self.loan_amount == 0.0 and self.purchase_price > 0 and self.down_payment > 0:
            self.loan_amount = self.purchase_price - self.down_payment


@dataclass
class ScoreFactor:
    """A single scored factor with explanation."""
    category: str
    name: str
    value: str
    points: float
    max_points: float
    risk_level: RiskLevel
    explanation: str
    action_items: list = field(default_factory=list)


@dataclass
class UnderwritingResult:
    """Complete underwriting analysis result."""
    recommendation: AUSRecommendation
    total_score: float
    max_possible_score: float
    score_pct: float
    factors: list  # list of ScoreFactor
    compensating_factors: list  # list of str
    risk_flags: list  # list of str
    deal_structure_notes: list  # list of str
    approval_probability_pct: float

    # Key ratios
    front_end_dti: float
    back_end_dti: float
    ltv: float
    cltv: float

    # Pricing impact
    estimated_llpa: float  # loan-level price adjustment (bps)


# ---------------------------------------------------------------------------
# Scoring Engine
# ---------------------------------------------------------------------------

class UnderwritingEngine:
    """
    Core scoring engine that evaluates a borrower profile against AUS criteria.
    Mirrors DU/LP logic: credit, capacity, collateral, capital.
    """

    def analyze(self, borrower: BorrowerProfile) -> UnderwritingResult:
        factors = []
        compensating = []
        risk_flags = []
        deal_notes = []

        # --- 1. CREDIT SCORE ---
        credit_factor = self._score_credit(borrower)
        factors.append(credit_factor)

        # --- 2. CREDIT HISTORY ---
        history_factor = self._score_credit_history(borrower)
        factors.append(history_factor)
        if borrower.late_payments_12mo > 0:
            risk_flags.append(f"Late payments in last 12 months ({borrower.late_payments_12mo}x)")
        if borrower.bankruptcy_months_ago < 48:
            risk_flags.append(f"Bankruptcy {borrower.bankruptcy_months_ago} months ago (need 48+ for conventional)")
        if borrower.foreclosure_months_ago < 84:
            risk_flags.append(f"Foreclosure {borrower.foreclosure_months_ago} months ago (need 84+ for conventional)")

        # --- 3. CREDIT DEPTH ---
        depth_factor = self._score_credit_depth(borrower)
        factors.append(depth_factor)

        # --- 4. CREDIT UTILIZATION ---
        util_factor = self._score_utilization(borrower)
        factors.append(util_factor)

        # --- 5. DTI (CAPACITY) ---
        front_dti, back_dti = self._calculate_dti(borrower)
        dti_factor = self._score_dti(back_dti, borrower)
        factors.append(dti_factor)

        # --- 6. LTV (COLLATERAL) ---
        ltv, cltv = self._calculate_ltv(borrower)
        ltv_factor = self._score_ltv(ltv, borrower)
        factors.append(ltv_factor)

        # --- 7. RESERVES (CAPITAL) ---
        reserves = self._calculate_reserves_months(borrower)
        reserves_factor = self._score_reserves(reserves, borrower)
        factors.append(reserves_factor)
        if reserves >= 6:
            compensating.append(f"Strong reserves: {reserves:.1f} months PITIA")

        # --- 8. EMPLOYMENT STABILITY ---
        emp_factor = self._score_employment(borrower)
        factors.append(emp_factor)
        if borrower.employment_months >= 24:
            compensating.append(f"Stable employment: {borrower.employment_months // 12}+ years")

        # --- 9. PROPERTY TYPE RISK ---
        prop_factor = self._score_property_type(borrower)
        factors.append(prop_factor)

        # --- 10. OCCUPANCY ---
        occ_factor = self._score_occupancy(borrower)
        factors.append(occ_factor)

        # --- 11. LOAN PURPOSE ---
        purpose_factor = self._score_loan_purpose(borrower)
        factors.append(purpose_factor)

        # --- 12. DOCUMENTATION TYPE ---
        doc_factor = self._score_doc_type(borrower)
        factors.append(doc_factor)

        # --- 13. RESIDUAL INCOME CHECK ---
        residual = self._calculate_residual_income(borrower)
        if residual > 2500:
            compensating.append(f"Strong residual income: ${residual:,.0f}/mo after all debts")

        # --- 14. DSCR (investment only) ---
        if borrower.occupancy == OccupancyType.INVESTMENT and borrower.monthly_rental_income > 0:
            dscr = borrower.monthly_rental_income / borrower.proposed_monthly_pitia if borrower.proposed_monthly_pitia > 0 else 0
            if dscr >= 1.25:
                compensating.append(f"Strong DSCR: {dscr:.2f}x")

        # Additional compensating factors
        if borrower.credit_score >= 740:
            compensating.append(f"Excellent credit: {borrower.credit_score}")
        if back_dti <= 36:
            compensating.append(f"Conservative DTI: {back_dti:.1f}%")
        if ltv <= 75:
            compensating.append(f"Strong equity position: {100 - ltv:.1f}% equity")
        total_income = borrower.monthly_gross_income + borrower.co_borrower_monthly_income
        if total_income > 0 and borrower.down_payment > 0:
            down_pmt_months = borrower.down_payment / total_income
            if down_pmt_months <= 12:
                compensating.append("Down payment < 12 months income (ability to save)")

        # --- AGGREGATE SCORING ---
        total_score = sum(f.points for f in factors)
        max_score = sum(f.max_points for f in factors)
        score_pct = (total_score / max_score * 100) if max_score > 0 else 0

        # LLPA estimation
        llpa = self._estimate_llpa(borrower, ltv)

        # Determine recommendation
        recommendation = self._determine_recommendation(
            score_pct, back_dti, ltv, borrower, risk_flags, compensating
        )

        # Approval probability
        approval_prob = self._estimate_approval_probability(
            score_pct, back_dti, ltv, borrower, risk_flags, len(compensating)
        )

        # Deal structure notes
        deal_notes = self._generate_deal_notes(
            borrower, front_dti, back_dti, ltv, reserves, score_pct, risk_flags, compensating
        )

        return UnderwritingResult(
            recommendation=recommendation,
            total_score=round(total_score, 1),
            max_possible_score=round(max_score, 1),
            score_pct=round(score_pct, 1),
            factors=factors,
            compensating_factors=compensating,
            risk_flags=risk_flags,
            deal_structure_notes=deal_notes,
            approval_probability_pct=round(approval_prob, 1),
            front_end_dti=round(front_dti, 2),
            back_end_dti=round(back_dti, 2),
            ltv=round(ltv, 2),
            cltv=round(cltv, 2),
            estimated_llpa=round(llpa, 3),
        )

    # ------------------------------------------------------------------
    # Individual scoring methods
    # ------------------------------------------------------------------

    def _score_credit(self, b: BorrowerProfile) -> ScoreFactor:
        score = b.credit_score
        max_pts = 100
        # Use representative score (lower of borrower / co-borrower if applicable)
        rep_score = score
        if b.co_borrower_credit_score is not None:
            rep_score = min(score, b.co_borrower_credit_score)

        for (low, high), info in CREDIT_TIER_MAP.items():
            if low <= rep_score <= high:
                pts = info["weight"] * max_pts
                risk = RiskLevel.LOW if pts >= 75 else RiskLevel.MODERATE if pts >= 50 else RiskLevel.HIGH if pts >= 30 else RiskLevel.VERY_HIGH
                actions = []
                if rep_score < 740:
                    actions.append(f"Target 740+ for best pricing (currently {rep_score})")
                if b.credit_utilization_pct > 30:
                    actions.append(f"Reduce utilization from {b.credit_utilization_pct:.0f}% to <30% (pay down {self._utilization_paydown(b)})")
                if rep_score < 620:
                    actions.append("Consider FHA (580 min) or VA (no FICO floor at some lenders)")
                    actions.append("Consider Non-QM products if conventional/govt won't work")
                return ScoreFactor(
                    category="Credit",
                    name="Credit Score Tier",
                    value=f"{rep_score} ({info['label']})",
                    points=round(pts, 1),
                    max_points=max_pts,
                    risk_level=risk,
                    explanation=f"Representative FICO {rep_score} falls in '{info['label']}' tier. LLPA adjustment: {info['llpa_adj']:+.2f}%",
                    action_items=actions,
                )

        return ScoreFactor("Credit", "Credit Score Tier", str(rep_score), 0, max_pts,
                           RiskLevel.VERY_HIGH, "Score outside known ranges", [])

    def _score_credit_history(self, b: BorrowerProfile) -> ScoreFactor:
        max_pts = 60
        pts = max_pts
        actions = []

        # Deductions
        pts -= b.late_payments_12mo * 20
        pts -= b.late_payments_24mo * 8
        if b.bankruptcy_months_ago < 48:
            pts -= 30
            actions.append(f"Wait until {48 - b.bankruptcy_months_ago} more months post-BK for conventional")
            actions.append("FHA allows 24 months post-BK discharge")
        elif b.bankruptcy_months_ago < 24:
            pts -= 50
        if b.foreclosure_months_ago < 84:
            pts -= 25
            actions.append(f"Wait {84 - b.foreclosure_months_ago} more months post-foreclosure (conventional)")
            actions.append("FHA allows 36 months post-foreclosure")
        if b.collections_amount > 0:
            if b.collections_amount > 2000:
                pts -= 10
                actions.append(f"Pay/settle collections over $2,000 (current: ${b.collections_amount:,.0f})")
            else:
                pts -= 3

        if b.late_payments_12mo > 0:
            actions.append("Establish 12 months of perfect payment history before applying")

        pts = max(0, pts)
        risk = RiskLevel.LOW if pts >= 45 else RiskLevel.MODERATE if pts >= 30 else RiskLevel.HIGH
        return ScoreFactor(
            category="Credit",
            name="Credit History / Derogatory Events",
            value=f"Late 12mo: {b.late_payments_12mo}, Late 24mo: {b.late_payments_24mo}, BK: {b.bankruptcy_months_ago}mo, FC: {b.foreclosure_months_ago}mo",
            points=round(pts, 1),
            max_points=max_pts,
            risk_level=risk,
            explanation="AUS heavily penalizes recent lates, BK, and foreclosure. Clean 12-24 month history is critical.",
            action_items=actions,
        )

    def _score_credit_depth(self, b: BorrowerProfile) -> ScoreFactor:
        max_pts = 30
        pts = 0
        actions = []

        if b.number_of_tradelines >= 5:
            pts += 15
        elif b.number_of_tradelines >= 3:
            pts += 10
        else:
            pts += 3
            actions.append(f"Build credit depth: add authorized user accounts or secured cards (currently {b.number_of_tradelines} tradelines)")

        if b.oldest_tradeline_months >= 84:
            pts += 15
        elif b.oldest_tradeline_months >= 48:
            pts += 10
        elif b.oldest_tradeline_months >= 24:
            pts += 5
        else:
            pts += 1
            actions.append("Credit file is thin/new — consider adding as authorized user on seasoned account")

        risk = RiskLevel.LOW if pts >= 22 else RiskLevel.MODERATE if pts >= 12 else RiskLevel.HIGH
        return ScoreFactor(
            category="Credit",
            name="Credit Depth / File Thickness",
            value=f"{b.number_of_tradelines} tradelines, oldest {b.oldest_tradeline_months} months",
            points=round(pts, 1),
            max_points=max_pts,
            risk_level=risk,
            explanation="DU/LP reward thick files with seasoned tradelines. Thin files get fewer compensating factor credits.",
            action_items=actions,
        )

    def _score_utilization(self, b: BorrowerProfile) -> ScoreFactor:
        max_pts = 40
        util = b.credit_utilization_pct
        actions = []

        if util <= 10:
            pts = 40
        elif util <= 20:
            pts = 35
        elif util <= 30:
            pts = 28
        elif util <= 50:
            pts = 18
            actions.append(f"Pay down revolving balances from {util:.0f}% to <30% utilization")
        elif util <= 70:
            pts = 10
            actions.append(f"Pay down revolving balances from {util:.0f}% to <30% utilization")
        else:
            pts = 3
            actions.append(f"CRITICAL: Utilization at {util:.0f}% — pay down to <30% before applying")
            actions.append("Each 10% reduction in utilization can boost FICO 10-30 points")

        risk = RiskLevel.LOW if pts >= 28 else RiskLevel.MODERATE if pts >= 18 else RiskLevel.HIGH
        return ScoreFactor(
            category="Credit",
            name="Credit Utilization",
            value=f"{util:.1f}%",
            points=round(pts, 1),
            max_points=max_pts,
            risk_level=risk,
            explanation="Utilization is the #1 quickest lever to move FICO. AUS sees high utilization as overextension.",
            action_items=actions,
        )

    def _calculate_dti(self, b: BorrowerProfile):
        total_income = b.monthly_gross_income + b.co_borrower_monthly_income
        if total_income == 0:
            return 0, 0
        front_dti = (b.proposed_monthly_pitia / total_income) * 100
        back_dti = ((b.proposed_monthly_pitia + b.monthly_debt_payments) / total_income) * 100
        return front_dti, back_dti

    def _score_dti(self, back_dti: float, b: BorrowerProfile) -> ScoreFactor:
        max_pts = 100
        actions = []

        if back_dti <= 28:
            pts = 100
        elif back_dti <= 33:
            pts = 90
        elif back_dti <= 36:
            pts = 80
        elif back_dti <= 40:
            pts = 65
        elif back_dti <= 43:
            pts = 50
            actions.append("At 43% DTI — right at QM limit. Pay off smallest debts to create cushion.")
        elif back_dti <= 45:
            pts = 35
            actions.append("Over 43% QM limit — need strong compensating factors (reserves, credit, residual income)")
            actions.append("Consider paying off debts to bring DTI below 43%")
        elif back_dti <= 50:
            pts = 20
            actions.append("DTI 45-50% requires DU Approve/Eligible with 2+ compensating factors")
            actions.append(self._dti_reduction_strategy(b, 43.0))
        else:
            pts = 5
            actions.append(f"DTI {back_dti:.1f}% exceeds most program limits")
            actions.append(self._dti_reduction_strategy(b, 43.0))
            actions.append("Consider adding co-borrower income")
            actions.append("Explore Non-QM or bank statement programs with higher DTI allowances")

        risk = RiskLevel.LOW if pts >= 65 else RiskLevel.MODERATE if pts >= 40 else RiskLevel.HIGH if pts >= 20 else RiskLevel.VERY_HIGH
        return ScoreFactor(
            category="Capacity",
            name="Debt-to-Income Ratio (Back-End)",
            value=f"{back_dti:.1f}%",
            points=round(pts, 1),
            max_points=max_pts,
            risk_level=risk,
            explanation=f"Back-end DTI at {back_dti:.1f}%. QM limit 43%, DU can go to 50% with compensating factors, FHA to 57%.",
            action_items=actions,
        )

    def _calculate_ltv(self, b: BorrowerProfile):
        value = min(b.purchase_price, b.appraised_value) if b.loan_purpose == LoanPurpose.PURCHASE else b.appraised_value
        if value == 0:
            return 0, 0
        ltv = (b.loan_amount / value) * 100
        cltv = ltv  # simplified — no subordinate liens in this model
        return ltv, cltv

    def _score_ltv(self, ltv: float, b: BorrowerProfile) -> ScoreFactor:
        max_pts = 80
        actions = []

        if ltv <= 60:
            pts = 80
        elif ltv <= 70:
            pts = 70
        elif ltv <= 75:
            pts = 60
        elif ltv <= 80:
            pts = 50
        elif ltv <= 85:
            pts = 35
            actions.append("LTV >80% requires PMI — factor into DTI calculation")
        elif ltv <= 90:
            pts = 25
            actions.append("Consider increasing down payment to 20% to eliminate PMI")
        elif ltv <= 95:
            pts = 15
            actions.append("High LTV — limited program options; credit score needs to be strong")
            actions.append("Consider gift funds or DPA programs to increase down payment")
        else:
            pts = 5
            actions.append("LTV >95% — only available through specific programs (VA 100%, USDA 100%, conventional 97%)")
            if b.credit_score < 680:
                actions.append("At this LTV, most lenders want 680+ FICO")

        # Check against program limits
        purpose_key = b.loan_purpose.value.split("_")[0] if "_" not in b.loan_purpose.value else b.loan_purpose.value
        occ_key = b.occupancy.value.split("_")[0]
        for (purp, occ), max_ltv in LTV_LIMITS.items():
            if purp.startswith(purpose_key[:4]) and occ.startswith(occ_key[:3]):
                if ltv > max_ltv:
                    actions.append(f"LTV {ltv:.1f}% exceeds {max_ltv}% limit for {b.loan_purpose.value}/{b.occupancy.value}")
                break

        risk = RiskLevel.LOW if pts >= 50 else RiskLevel.MODERATE if pts >= 30 else RiskLevel.HIGH
        return ScoreFactor(
            category="Collateral",
            name="Loan-to-Value Ratio",
            value=f"{ltv:.1f}%",
            points=round(pts, 1),
            max_points=max_pts,
            risk_level=risk,
            explanation=f"LTV at {ltv:.1f}%. Lower LTV = better pricing, more program options, stronger AUS score.",
            action_items=actions,
        )

    def _calculate_reserves_months(self, b: BorrowerProfile) -> float:
        if b.months_reserves > 0:
            return b.months_reserves
        pitia = b.proposed_monthly_pitia
        if pitia == 0:
            return 0
        effective_assets = b.total_liquid_assets + (b.retirement_assets * 0.6)
        reserves_after_closing = effective_assets - b.down_payment
        return max(0, reserves_after_closing / pitia)

    def _score_reserves(self, months: float, b: BorrowerProfile) -> ScoreFactor:
        max_pts = 60
        actions = []

        for (low, high), info in RESERVES_SCORING.items():
            if low <= months <= high:
                pts = info["points"]
                label = info["label"]
                break
        else:
            pts = 0
            label = "No reserves"

        if months < 2:
            actions.append("Build up at least 2 months PITIA in reserves before applying")
            actions.append("6+ months reserves is a key compensating factor for AUS")
        elif months < 6:
            actions.append(f"Currently {months:.1f} months — build to 6+ months for compensating factor credit")

        # Investment property needs more
        if b.occupancy == OccupancyType.INVESTMENT and months < 6:
            actions.append("Investment property requires minimum 6 months reserves (many lenders want 6-12)")

        risk = RiskLevel.LOW if pts >= 30 else RiskLevel.MODERATE if pts >= 15 else RiskLevel.HIGH
        return ScoreFactor(
            category="Capital",
            name="Reserves (Months PITIA)",
            value=f"{months:.1f} months ({label})",
            points=round(pts, 1),
            max_points=max_pts,
            risk_level=risk,
            explanation=f"{months:.1f} months of reserves. DU gives significant weight to reserves — it's a top compensating factor.",
            action_items=actions,
        )

    def _score_employment(self, b: BorrowerProfile) -> ScoreFactor:
        max_pts = 40
        actions = []

        if b.self_employed:
            if b.years_self_employed >= 5:
                pts = 35
            elif b.years_self_employed >= 2:
                pts = 25
            else:
                pts = 10
                actions.append("Self-employed <2 years is difficult — most lenders require 2+ year history")
                actions.append("Consider bank statement programs (12-24 month average deposits)")
        else:
            if b.employment_months >= 24:
                pts = 40
            elif b.employment_months >= 12:
                pts = 30
            elif b.employment_months >= 6:
                pts = 20
                actions.append("Less than 2 years at current job — be ready to document prior employment")
            else:
                pts = 10
                actions.append("Employment <6 months — high risk factor. Document job offer letter, prior history.")

        risk = RiskLevel.LOW if pts >= 30 else RiskLevel.MODERATE if pts >= 20 else RiskLevel.HIGH
        return ScoreFactor(
            category="Capacity",
            name="Employment Stability",
            value=f"{'Self-employed' if b.self_employed else 'W-2'} — {b.employment_months} months",
            points=round(pts, 1),
            max_points=max_pts,
            risk_level=risk,
            explanation="AUS rewards employment longevity. 2+ years same employer/field is ideal.",
            action_items=actions,
        )

    def _score_property_type(self, b: BorrowerProfile) -> ScoreFactor:
        max_pts = 20
        prop_scores = {
            PropertyType.SFR: (20, RiskLevel.LOW, "Single-family is lowest risk — best pricing."),
            PropertyType.TOWNHOME: (18, RiskLevel.LOW, "Townhomes score nearly as well as SFR."),
            PropertyType.CONDO: (14, RiskLevel.MODERATE, "Condos have LLPA hits and need warrantable status."),
            PropertyType.MULTI_2_4: (10, RiskLevel.MODERATE, "2-4 unit has additional reserve requirements and tighter DTI."),
            PropertyType.MANUFACTURED: (6, RiskLevel.HIGH, "Manufactured homes have very limited program options and higher LLPA."),
        }
        pts, risk, expl = prop_scores.get(b.property_type, (10, RiskLevel.MODERATE, ""))
        actions = []
        if b.property_type == PropertyType.CONDO:
            actions.append("Ensure condo project is warrantable (check HOA questionnaire)")
        if b.property_type == PropertyType.MANUFACTURED:
            actions.append("Verify property meets HUD standards and is on permanent foundation")
        return ScoreFactor("Collateral", "Property Type", b.property_type.value, pts, max_pts, risk, expl, actions)

    def _score_occupancy(self, b: BorrowerProfile) -> ScoreFactor:
        max_pts = 20
        occ_scores = {
            OccupancyType.PRIMARY: (20, RiskLevel.LOW, "Owner-occupied is the gold standard — best rates and highest LTV."),
            OccupancyType.SECOND_HOME: (12, RiskLevel.MODERATE, "Second home has LLPA add-ons and tighter LTV limits."),
            OccupancyType.INVESTMENT: (6, RiskLevel.HIGH, "Investment properties have highest rates, lowest LTV, most reserves needed."),
        }
        pts, risk, expl = occ_scores.get(b.occupancy, (10, RiskLevel.MODERATE, ""))
        actions = []
        if b.occupancy == OccupancyType.INVESTMENT:
            actions.append("Investment property: expect 0.5-1.5% higher rate vs primary residence")
            actions.append("Consider house-hacking (live in one unit of multi-family) to qualify as primary")
        return ScoreFactor("Collateral", "Occupancy Type", b.occupancy.value, pts, max_pts, risk, expl, actions)

    def _score_loan_purpose(self, b: BorrowerProfile) -> ScoreFactor:
        max_pts = 15
        purpose_scores = {
            LoanPurpose.PURCHASE: (15, RiskLevel.LOW, "Purchase has best AUS treatment."),
            LoanPurpose.RATE_TERM_REFI: (12, RiskLevel.LOW, "Rate/term refi scores well — shows responsible refinancing."),
            LoanPurpose.CASH_OUT_REFI: (6, RiskLevel.MODERATE, "Cash-out refi has LLPA hits, lower max LTV, tighter underwriting."),
        }
        pts, risk, expl = purpose_scores.get(b.loan_purpose, (10, RiskLevel.MODERATE, ""))
        actions = []
        if b.loan_purpose == LoanPurpose.CASH_OUT_REFI:
            actions.append("Cash-out max 80% LTV (primary), 75% (investment/second home)")
            actions.append("Consider rate/term refi + HELOC instead to avoid cash-out LLPA penalty")
        return ScoreFactor("Deal Structure", "Loan Purpose", b.loan_purpose.value, pts, max_pts, risk, expl, actions)

    def _score_doc_type(self, b: BorrowerProfile) -> ScoreFactor:
        max_pts = 15
        doc_scores = {
            IncomeDocType.FULL_DOC: (15, RiskLevel.LOW, "Full documentation — strongest AUS treatment, best pricing."),
            IncomeDocType.BANK_STATEMENTS: (8, RiskLevel.MODERATE, "Bank statement loans are Non-QM — higher rates, but accessible for self-employed."),
            IncomeDocType.ASSET_DEPLETION: (6, RiskLevel.MODERATE, "Asset depletion is niche — works for retirees with large portfolios."),
            IncomeDocType.DSCR: (5, RiskLevel.HIGH, "DSCR loans don't use personal income — purely property cash flow based."),
        }
        pts, risk, expl = doc_scores.get(b.doc_type, (10, RiskLevel.MODERATE, ""))
        actions = []
        if b.doc_type != IncomeDocType.FULL_DOC:
            actions.append("Full doc (W-2, tax returns) always gets best AUS treatment if available")
        return ScoreFactor("Documentation", "Income Documentation", b.doc_type.value, pts, max_pts, risk, expl, actions)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _utilization_paydown(self, b: BorrowerProfile) -> str:
        """Estimate how much to pay down to reach target utilization."""
        if b.credit_utilization_pct <= 30 or b.total_liquid_assets == 0:
            return "N/A"
        # Rough estimate: assume total revolving limits ~ monthly_debt * 30 (very rough)
        estimated_balance = b.monthly_debt_payments * 20  # rough proxy
        target_balance = estimated_balance * (30 / max(b.credit_utilization_pct, 1))
        paydown = estimated_balance - target_balance
        return f"~${max(0, paydown):,.0f}" if paydown > 0 else "N/A"

    def _dti_reduction_strategy(self, b: BorrowerProfile, target_dti: float) -> str:
        total_income = b.monthly_gross_income + b.co_borrower_monthly_income
        if total_income == 0:
            return "Cannot calculate — no income provided"
        current_total_debt = b.proposed_monthly_pitia + b.monthly_debt_payments
        target_total_debt = total_income * (target_dti / 100)
        reduction_needed = current_total_debt - target_total_debt
        if reduction_needed <= 0:
            return "DTI already at/below target"
        return f"Reduce monthly debts by ${reduction_needed:,.0f}/mo to reach {target_dti}% DTI (pay off ~${reduction_needed * 30:,.0f} in installment/revolving debt)"

    def _calculate_residual_income(self, b: BorrowerProfile) -> float:
        total_income = b.monthly_gross_income + b.co_borrower_monthly_income
        total_debts = b.proposed_monthly_pitia + b.monthly_debt_payments
        return total_income - total_debts

    def _estimate_llpa(self, b: BorrowerProfile, ltv: float) -> float:
        """Estimate loan-level price adjustments (percentage points)."""
        llpa = 0.0
        # Credit score adjustment
        for (low, high), info in CREDIT_TIER_MAP.items():
            if low <= b.credit_score <= high:
                llpa += info["llpa_adj"]
                break

        # LTV adjustments
        if ltv > 95:
            llpa += 0.75
        elif ltv > 90:
            llpa += 0.50
        elif ltv > 80:
            llpa += 0.25

        # Cash-out adjustment
        if b.loan_purpose == LoanPurpose.CASH_OUT_REFI:
            llpa += 0.375

        # Investment property
        if b.occupancy == OccupancyType.INVESTMENT:
            llpa += 1.125
        elif b.occupancy == OccupancyType.SECOND_HOME:
            llpa += 0.625

        # Condo
        if b.property_type == PropertyType.CONDO:
            llpa += 0.25
        elif b.property_type == PropertyType.MANUFACTURED:
            llpa += 0.50
        elif b.property_type == PropertyType.MULTI_2_4:
            llpa += 0.25

        return llpa

    def _determine_recommendation(self, score_pct, back_dti, ltv, b, risk_flags, compensating):
        # Severe disqualifiers
        if b.bankruptcy_months_ago < 24 and b.doc_type == IncomeDocType.FULL_DOC:
            return AUSRecommendation.OUT_OF_SCOPE
        if b.foreclosure_months_ago < 36:
            return AUSRecommendation.OUT_OF_SCOPE

        num_comp = len(compensating)

        if score_pct >= 70 and back_dti <= 50 and len(risk_flags) == 0:
            return AUSRecommendation.APPROVE_ELIGIBLE
        elif score_pct >= 60 and back_dti <= 50 and num_comp >= 2:
            return AUSRecommendation.APPROVE_ELIGIBLE
        elif score_pct >= 55 and back_dti <= 55:
            return AUSRecommendation.APPROVE_INELIGIBLE
        elif score_pct >= 40:
            return AUSRecommendation.REFER_ELIGIBLE
        else:
            return AUSRecommendation.REFER_INELIGIBLE

    def _estimate_approval_probability(self, score_pct, back_dti, ltv, b, risk_flags, num_comp):
        prob = score_pct  # start with score percentage

        # DTI penalty
        if back_dti > 50:
            prob -= 25
        elif back_dti > 45:
            prob -= 15
        elif back_dti > 43:
            prob -= 8

        # LTV penalty
        if ltv > 95:
            prob -= 15
        elif ltv > 90:
            prob -= 8

        # Risk flags
        prob -= len(risk_flags) * 8

        # Compensating factor boost
        prob += min(num_comp * 3, 15)

        # Credit floor effect
        if b.credit_score < 620:
            prob -= 20
        elif b.credit_score < 660:
            prob -= 10

        return max(1, min(99, prob))

    def _generate_deal_notes(self, b, front_dti, back_dti, ltv, reserves, score_pct, risk_flags, compensating):
        notes = []

        notes.append("=" * 60)
        notes.append("DEAL STRUCTURE RECOMMENDATIONS")
        notes.append("=" * 60)

        # --- Program routing ---
        notes.append("")
        notes.append("--- BEST PROGRAM FIT ---")
        if b.credit_score >= 620 and back_dti <= 50 and ltv <= 97:
            notes.append("  -> CONVENTIONAL (Fannie/Freddie) — Run through DU first, then LP")
            if ltv > 80:
                notes.append("     PMI required — shop BPMI vs LPMI vs split premium")
        if b.credit_score >= 580 and back_dti <= 57:
            notes.append("  -> FHA — More forgiving on DTI (up to 57%) and credit (580+)")
            notes.append("     Upfront MIP 1.75% + annual MIP 0.55-1.05% (life of loan if <10% down)")
        if b.credit_score >= 580:  # VA has no official floor
            notes.append("  -> VA (if eligible) — No down payment, no PMI, residual income model")
            notes.append("     VA funding fee 1.25-3.3% (can be financed)")
        if ltv >= 100 and b.occupancy == OccupancyType.PRIMARY:
            notes.append("  -> USDA (if rural eligible) — 100% financing, income limits apply")

        # --- DTI optimization ---
        if back_dti > 43:
            notes.append("")
            notes.append("--- DTI REDUCTION STRATEGIES ---")
            total_income = b.monthly_gross_income + b.co_borrower_monthly_income
            target_debt = total_income * 0.43
            current_debt = b.proposed_monthly_pitia + b.monthly_debt_payments
            excess = current_debt - target_debt

            notes.append(f"  Current back-end DTI: {back_dti:.1f}%")
            notes.append(f"  Need to eliminate ${excess:,.0f}/mo in payments to hit 43%")
            notes.append(f"  Options:")
            notes.append(f"    1. Pay off revolving debts (${excess * 25:,.0f} approx balance)")
            notes.append(f"    2. Add co-borrower income of ${excess:,.0f}/mo to offset")
            notes.append(f"    3. Increase down payment to reduce loan amount/PITIA")
            notes.append(f"    4. Buy down rate to reduce monthly P&I")
            notes.append(f"    5. Consider longer amortization if not already 30-year")

        # --- Credit optimization ---
        if b.credit_score < 740:
            notes.append("")
            notes.append("--- CREDIT OPTIMIZATION ---")
            notes.append(f"  Current FICO: {b.credit_score}")
            if b.credit_utilization_pct > 30:
                notes.append(f"  [HIGH IMPACT] Reduce utilization from {b.credit_utilization_pct:.0f}% to <10%")
                notes.append(f"    -> Expected FICO boost: +20 to +50 points")
                notes.append(f"    -> Pay down cards BEFORE statement closing date")
            if b.late_payments_12mo > 0:
                notes.append(f"  [HIGH IMPACT] Wait for 12 months clean payment history")
            if b.number_of_tradelines < 3:
                notes.append(f"  [MEDIUM IMPACT] Add authorized user on seasoned account (instant tradeline)")
            notes.append(f"  Target thresholds: 620 (conv min), 660, 680, 700, 720, 740 (best pricing)")

        # --- LTV / Down payment ---
        if ltv > 80:
            notes.append("")
            notes.append("--- DOWN PAYMENT / LTV STRATEGIES ---")
            value = min(b.purchase_price, b.appraised_value) if b.purchase_price > 0 else b.appraised_value
            target_80 = value * 0.80
            additional_down = b.loan_amount - target_80
            notes.append(f"  Current LTV: {ltv:.1f}%")
            notes.append(f"  Additional ${additional_down:,.0f} down payment reaches 80% LTV (no PMI)")
            notes.append(f"  Sources for down payment:")
            notes.append(f"    1. Gift funds (family — need gift letter)")
            notes.append(f"    2. Down Payment Assistance (DPA) programs")
            notes.append(f"    3. Employer assistance programs")
            notes.append(f"    4. 401k loan (doesn't count as debt on most AUS)")
            notes.append(f"    5. Seller concessions (up to 3-6% depending on LTV)")

        # --- Reserves strategy ---
        if reserves < 6:
            notes.append("")
            notes.append("--- RESERVES BUILDING ---")
            notes.append(f"  Current reserves: {reserves:.1f} months")
            notes.append(f"  Target: 6+ months (key DU compensating factor)")
            pitia = b.proposed_monthly_pitia
            if pitia > 0:
                needed = (6 - reserves) * pitia
                notes.append(f"  Need approximately ${needed:,.0f} more in liquid assets")
                notes.append(f"  Acceptable reserves: checking, savings, money market, stocks, bonds")
                notes.append(f"  Retirement accounts counted at 60% of vested balance")

        # --- Compensating factors summary ---
        if compensating:
            notes.append("")
            notes.append("--- ACTIVE COMPENSATING FACTORS ---")
            for i, cf in enumerate(compensating, 1):
                notes.append(f"  {i}. {cf}")
            notes.append(f"  (DU requires 2+ compensating factors for DTI exceptions)")

        # --- Risk flags ---
        if risk_flags:
            notes.append("")
            notes.append("--- RISK FLAGS TO ADDRESS ---")
            for i, rf in enumerate(risk_flags, 1):
                notes.append(f"  {i}. {rf}")

        # --- Submission strategy ---
        notes.append("")
        notes.append("--- AUS SUBMISSION STRATEGY ---")
        notes.append("  1. Run DU (Desktop Underwriter) first — more flexible on DTI")
        notes.append("  2. If DU gets Refer, run LP (Loan Product Advisor) — different algorithm")
        notes.append("  3. If both Refer, check FHA/VA eligibility")
        notes.append("  4. If government doesn't work, explore Non-QM options")
        notes.append("  5. Re-run AUS after any credit or debt changes to get updated findings")

        return notes
