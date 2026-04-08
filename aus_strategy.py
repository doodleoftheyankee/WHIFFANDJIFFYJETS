"""
AUS Strategy Analyzer
=====================
Maps borrower profiles against specific AUS platform rules (DU, LP, FHA TOTAL,
VA) and determines which system gives the best chance of automated approval.
Includes detailed guideline references and layered risk matrix.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from underwriting_engine import (
    BorrowerProfile, LoanPurpose, OccupancyType, PropertyType, IncomeDocType,
)


class AUSPlatform(Enum):
    DU = "Desktop Underwriter (Fannie Mae)"
    LP = "Loan Product Advisor (Freddie Mac)"
    FHA_TOTAL = "FHA TOTAL Scorecard"
    VA_AUS = "VA Automated (WebLGY)"


@dataclass
class ProgramEligibility:
    """Eligibility result for a specific AUS/program."""
    platform: AUSPlatform
    eligible: bool
    confidence: str  # "High", "Medium", "Low"
    max_dti_allowed: float
    max_ltv_allowed: float
    min_credit_score: int
    min_reserves_months: float
    estimated_rate_adjustment: float  # vs base rate
    key_advantages: list = field(default_factory=list)
    key_risks: list = field(default_factory=list)
    guideline_notes: list = field(default_factory=list)
    submission_tips: list = field(default_factory=list)
    priority_rank: int = 0  # 1 = best option


@dataclass
class LayeredRisk:
    """Risk layering analysis — AUS penalizes stacked risk factors."""
    layer_count: int
    layers: list  # list of str descriptions
    assessment: str
    max_layers_for_approval: int
    recommendation: str


class AUSStrategyAnalyzer:
    """
    Analyzes which AUS platform and loan program gives the best
    automated approval probability for a given borrower profile.
    """

    def analyze(self, borrower: BorrowerProfile) -> dict:
        """
        Full analysis: program eligibility, risk layering, submission strategy.
        """
        # Evaluate each platform
        du_result = self._evaluate_du(borrower)
        lp_result = self._evaluate_lp(borrower)
        fha_result = self._evaluate_fha(borrower)
        va_result = self._evaluate_va(borrower)

        programs = [du_result, lp_result, fha_result, va_result]

        # Rank programs
        eligible_programs = [p for p in programs if p.eligible]
        eligible_programs.sort(key=lambda p: (
            -{"High": 3, "Medium": 2, "Low": 1}.get(p.confidence, 0),
            p.estimated_rate_adjustment,
        ))
        for i, prog in enumerate(eligible_programs):
            prog.priority_rank = i + 1

        # Risk layering analysis
        risk_layers = self._analyze_risk_layers(borrower)

        # Submission strategy
        strategy = self._build_submission_strategy(borrower, eligible_programs, risk_layers)

        # Guideline quick-reference
        guidelines = self._build_guideline_reference(borrower)

        return {
            "programs": programs,
            "eligible_programs": eligible_programs,
            "risk_layers": risk_layers,
            "submission_strategy": strategy,
            "guideline_reference": guidelines,
        }

    # ------------------------------------------------------------------
    # Platform evaluations
    # ------------------------------------------------------------------

    def _evaluate_du(self, b: BorrowerProfile) -> ProgramEligibility:
        """Desktop Underwriter (Fannie Mae) evaluation."""
        eligible = True
        confidence = "High"
        risks = []
        advantages = []
        notes = []
        tips = []

        # Credit minimums
        min_fico = 620
        if b.credit_score < min_fico:
            eligible = False
            risks.append(f"FICO {b.credit_score} below DU minimum {min_fico}")

        # DTI limits
        max_dti = 50.0  # DU can go to 50% with compensating factors
        total_income = b.monthly_gross_income + b.co_borrower_monthly_income
        if total_income > 0:
            back_dti = ((b.proposed_monthly_pitia + b.monthly_debt_payments) / total_income) * 100
            if back_dti > 50:
                eligible = False
                risks.append(f"DTI {back_dti:.1f}% exceeds DU max 50%")
            elif back_dti > 45:
                confidence = "Medium"
                notes.append("DTI 45-50% requires strong compensating factors")

        # LTV limits
        max_ltv = 97.0 if b.occupancy == OccupancyType.PRIMARY else 90.0 if b.occupancy == OccupancyType.SECOND_HOME else 85.0
        if b.loan_purpose == LoanPurpose.CASH_OUT_REFI:
            max_ltv = 80.0 if b.occupancy == OccupancyType.PRIMARY else 75.0

        value = min(b.purchase_price, b.appraised_value) if b.loan_purpose == LoanPurpose.PURCHASE else b.appraised_value
        if value > 0:
            ltv = (b.loan_amount / value) * 100
            if ltv > max_ltv:
                eligible = False
                risks.append(f"LTV {ltv:.1f}% exceeds DU max {max_ltv}% for {b.occupancy.value}/{b.loan_purpose.value}")

        # Derogatory events
        if b.bankruptcy_months_ago < 48:
            eligible = False
            risks.append(f"BK only {b.bankruptcy_months_ago} months ago — DU requires 48+ months")
        if b.foreclosure_months_ago < 84:
            eligible = False
            risks.append(f"Foreclosure only {b.foreclosure_months_ago} months ago — DU requires 84+ months")

        # Reserves
        min_reserves = 0.0
        if b.occupancy == OccupancyType.INVESTMENT:
            min_reserves = 6.0
        elif b.occupancy == OccupancyType.SECOND_HOME:
            min_reserves = 2.0

        # Advantages
        advantages.append("Most widely used AUS — highest lender familiarity")
        advantages.append("Can approve DTI up to 50% with compensating factors")
        advantages.append("Allows 97% LTV on primary purchase")
        if b.credit_score >= 740:
            advantages.append("Excellent FICO gets best LLPA pricing through DU")

        # Tips
        tips.append("Submit DU FIRST before LP — DU is generally more forgiving on DTI")
        tips.append("If DU returns 'Refer', check findings carefully for specific issues")
        tips.append("DU allows resubmission — fix issues and rerun immediately")
        if b.credit_score >= 680 and b.credit_score < 720:
            tips.append("At FICO boundary — a rapid rescore of +20 pts could significantly improve LLPA")

        notes.append(f"Fannie Mae Selling Guide B3-5.1: DTI max 50% for DU Approve")
        notes.append(f"LLPA matrix applies — check current Fannie LLPA grid for {b.credit_score} FICO / {max_ltv}% LTV")

        return ProgramEligibility(
            platform=AUSPlatform.DU,
            eligible=eligible,
            confidence=confidence,
            max_dti_allowed=max_dti,
            max_ltv_allowed=max_ltv,
            min_credit_score=min_fico,
            min_reserves_months=min_reserves,
            estimated_rate_adjustment=0.0,  # DU is baseline
            key_advantages=advantages,
            key_risks=risks,
            guideline_notes=notes,
            submission_tips=tips,
        )

    def _evaluate_lp(self, b: BorrowerProfile) -> ProgramEligibility:
        """Loan Product Advisor (Freddie Mac) evaluation."""
        eligible = True
        confidence = "High"
        risks = []
        advantages = []
        notes = []
        tips = []

        min_fico = 620
        if b.credit_score < min_fico:
            eligible = False
            risks.append(f"FICO {b.credit_score} below LP minimum {min_fico}")

        max_dti = 50.0
        total_income = b.monthly_gross_income + b.co_borrower_monthly_income
        if total_income > 0:
            back_dti = ((b.proposed_monthly_pitia + b.monthly_debt_payments) / total_income) * 100
            if back_dti > 50:
                eligible = False
                risks.append(f"DTI {back_dti:.1f}% exceeds LP max 50%")
            elif back_dti > 45:
                confidence = "Medium"

        max_ltv = 97.0 if b.occupancy == OccupancyType.PRIMARY else 90.0 if b.occupancy == OccupancyType.SECOND_HOME else 85.0
        if b.loan_purpose == LoanPurpose.CASH_OUT_REFI:
            max_ltv = 80.0 if b.occupancy == OccupancyType.PRIMARY else 75.0

        if b.bankruptcy_months_ago < 48:
            eligible = False
            risks.append("BK too recent for conventional")
        if b.foreclosure_months_ago < 84:
            eligible = False
            risks.append("Foreclosure too recent for conventional")

        min_reserves = 0.0
        if b.occupancy == OccupancyType.INVESTMENT:
            min_reserves = 6.0

        advantages.append("LP uses different algorithm than DU — may approve files DU refers")
        advantages.append("Better treatment of non-traditional credit in some cases")
        advantages.append("LP may give Accept on borderline DTI cases where DU gives Refer")
        advantages.append("Freddie Mac Home Possible: 3% down for low-moderate income borrowers")

        tips.append("Always run LP if DU returns Refer — different algorithm may produce Accept")
        tips.append("LP Accept ≈ DU Approve/Eligible — same approval level, different name")
        tips.append("LP may be more favorable for borrowers with shorter credit history")
        tips.append("Check Freddie Mac LLPA grid — sometimes different from Fannie")

        notes.append("Freddie Mac Guide 5501.1: Similar DTI framework to DU")
        notes.append("LP uses 'Accept' terminology vs DU's 'Approve'")

        return ProgramEligibility(
            platform=AUSPlatform.LP,
            eligible=eligible,
            confidence=confidence,
            max_dti_allowed=max_dti,
            max_ltv_allowed=max_ltv,
            min_credit_score=min_fico,
            min_reserves_months=min_reserves,
            estimated_rate_adjustment=0.0,
            key_advantages=advantages,
            key_risks=risks,
            guideline_notes=notes,
            submission_tips=tips,
        )

    def _evaluate_fha(self, b: BorrowerProfile) -> ProgramEligibility:
        """FHA TOTAL Scorecard evaluation."""
        eligible = True
        confidence = "High"
        risks = []
        advantages = []
        notes = []
        tips = []

        # Credit
        min_fico = 580  # 3.5% down; 500-579 needs 10% down
        if b.credit_score < 500:
            eligible = False
            risks.append("FICO below 500 — FHA floor")
        elif b.credit_score < 580:
            confidence = "Medium"
            notes.append("FICO 500-579 requires 10% minimum down payment")

        # DTI
        max_dti = 57.0  # FHA can go to 57% with compensating factors
        total_income = b.monthly_gross_income + b.co_borrower_monthly_income
        if total_income > 0:
            back_dti = ((b.proposed_monthly_pitia + b.monthly_debt_payments) / total_income) * 100
            if back_dti > 57:
                eligible = False
                risks.append(f"DTI {back_dti:.1f}% exceeds FHA max 57%")
            elif back_dti > 50:
                confidence = "Medium"
                notes.append("DTI 50-57% needs strong compensating factors for TOTAL Approve")
            elif back_dti > 43:
                notes.append("DTI 43-50% may still get TOTAL Approve with residual income")

        # LTV
        max_ltv = 96.5  # 3.5% min down
        if b.credit_score < 580:
            max_ltv = 90.0  # 10% down required

        # BK/FC seasoning
        if b.bankruptcy_months_ago < 24:
            eligible = False
            risks.append(f"BK {b.bankruptcy_months_ago} months ago — FHA requires 24+ months")
        elif b.bankruptcy_months_ago < 48:
            advantages.append(f"FHA accepts BK at 24+ months (currently {b.bankruptcy_months_ago} mo) — conv requires 48")

        if b.foreclosure_months_ago < 36:
            eligible = False
            risks.append(f"Foreclosure {b.foreclosure_months_ago} months ago — FHA requires 36+ months")
        elif b.foreclosure_months_ago < 84:
            advantages.append(f"FHA accepts foreclosure at 36+ months — conv requires 84")

        # Investment property not allowed
        if b.occupancy == OccupancyType.INVESTMENT:
            eligible = False
            risks.append("FHA does not allow investment properties")
        if b.occupancy == OccupancyType.SECOND_HOME:
            eligible = False
            risks.append("FHA does not allow second homes")

        # FHA advantages
        advantages.append("Lowest credit score requirement (580 for 3.5% down)")
        advantages.append("DTI up to 57% with compensating factors (vs 50% conventional)")
        advantages.append("More lenient on credit events (BK 24mo, FC 36mo)")
        advantages.append("Manual underwrite option if TOTAL returns Refer")
        advantages.append("Assumable loan — valuable in high-rate environment")

        # FHA disadvantages
        risks.append("MIP for life of loan if <10% down (expensive long-term)")
        risks.append("Upfront MIP 1.75% added to loan balance")

        tips.append("FHA TOTAL Scorecard weighs credit history heavily — clean 12 months is critical")
        tips.append("If TOTAL returns Refer, file can still be manually underwritten")
        tips.append("FHA allows non-occupant co-borrowers (parents co-signing)")
        tips.append("Consider FHA for FICO 580-620 range where conv pricing is punitive")
        if b.credit_score >= 680:
            tips.append("With 680+ FICO, compare FHA MIP cost vs conventional PMI — conv may be cheaper")

        notes.append("HUD Handbook 4000.1: FHA underwriting guidelines")
        notes.append("TOTAL Scorecard is FHA's AUS — similar to DU but different thresholds")

        mip_annual = 0.55 if b.loan_amount <= 726200 else 0.75
        rate_adj = mip_annual / 100  # approximate rate equivalent of MIP

        return ProgramEligibility(
            platform=AUSPlatform.FHA_TOTAL,
            eligible=eligible,
            confidence=confidence,
            max_dti_allowed=max_dti,
            max_ltv_allowed=max_ltv,
            min_credit_score=min_fico,
            min_reserves_months=0,  # FHA has no minimum reserves for 1-2 unit
            estimated_rate_adjustment=rate_adj,
            key_advantages=advantages,
            key_risks=risks,
            guideline_notes=notes,
            submission_tips=tips,
        )

    def _evaluate_va(self, b: BorrowerProfile) -> ProgramEligibility:
        """VA AUS evaluation."""
        eligible = True  # We can't verify veteran status, so mark as potentially eligible
        confidence = "Medium"  # Unknown eligibility
        risks = []
        advantages = []
        notes = []
        tips = []

        # VA has no official FICO minimum, but lenders overlay
        min_fico = 580  # most VA lenders
        if b.credit_score < 580:
            confidence = "Low"
            risks.append("Most VA lenders require 580+ FICO (some as low as 500)")

        # DTI — VA uses residual income, not hard DTI cap
        max_dti = 60.0  # theoretical — residual income is the real test
        total_income = b.monthly_gross_income + b.co_borrower_monthly_income
        residual = 0
        if total_income > 0:
            back_dti = ((b.proposed_monthly_pitia + b.monthly_debt_payments) / total_income) * 100
            residual = total_income - (b.proposed_monthly_pitia + b.monthly_debt_payments)
            if back_dti > 41:
                notes.append(f"DTI {back_dti:.1f}% triggers VA manual review, but no automatic decline")

        # LTV — VA allows 100%
        max_ltv = 100.0

        # VA doesn't care about occupancy type for eligible borrowers
        if b.occupancy == OccupancyType.INVESTMENT:
            eligible = False
            risks.append("VA requires owner-occupancy")

        # BK/FC — VA is more lenient
        if b.bankruptcy_months_ago < 24:
            risks.append("VA typically requires 24 months post-BK (Chapter 7)")
            notes.append("Chapter 13 BK: can apply after 12 months of on-time plan payments")
        if b.foreclosure_months_ago < 24:
            risks.append("VA typically requires 24 months post-foreclosure")

        advantages.append("0% down payment — 100% financing")
        advantages.append("NO PMI/MIP — significant monthly savings")
        advantages.append("No hard DTI limit — uses residual income model")
        advantages.append("No FICO floor from VA (lender overlays apply, typically 580-620)")
        advantages.append("More forgiving on BK/FC seasoning (24 months)")
        advantages.append("Funding fee can be financed into loan")
        advantages.append("Assumable — transferable to another eligible veteran")

        if residual > 0:
            tips.append(f"Residual income: ${residual:,.0f}/mo — VA requires region-specific minimums")

        tips.append("Get Certificate of Eligibility (COE) first — confirms entitlement")
        tips.append("VA residual income minimums vary by region and family size")
        tips.append("Disabled veterans may be exempt from funding fee")
        tips.append("VA allows seller concessions up to 4% of sale price")
        tips.append("VA IRRRL (streamline refi) requires no appraisal or income verification")

        notes.append("VA Pamphlet 26-7: VA Lenders Handbook")
        notes.append("Residual income is king for VA — calculate carefully based on region")

        return ProgramEligibility(
            platform=AUSPlatform.VA_AUS,
            eligible=eligible,
            confidence=confidence,
            max_dti_allowed=max_dti,
            max_ltv_allowed=max_ltv,
            min_credit_score=min_fico,
            min_reserves_months=0,
            estimated_rate_adjustment=-0.25,  # VA rates often better than conventional
            key_advantages=advantages,
            key_risks=risks,
            guideline_notes=notes,
            submission_tips=tips,
        )

    # ------------------------------------------------------------------
    # Risk layering
    # ------------------------------------------------------------------

    def _analyze_risk_layers(self, b: BorrowerProfile) -> LayeredRisk:
        """
        AUS systems penalize 'risk layering' — stacking multiple risk factors.
        This identifies all active risk layers.
        """
        layers = []

        # Credit layers
        if b.credit_score < 680:
            layers.append(f"Low credit score ({b.credit_score})")
        if b.credit_utilization_pct > 50:
            layers.append(f"High utilization ({b.credit_utilization_pct:.0f}%)")
        if b.late_payments_12mo > 0:
            layers.append(f"Recent delinquency ({b.late_payments_12mo} lates in 12mo)")
        if b.number_of_tradelines < 3:
            layers.append(f"Thin credit file ({b.number_of_tradelines} tradelines)")

        # Capacity layers
        total_income = b.monthly_gross_income + b.co_borrower_monthly_income
        if total_income > 0:
            back_dti = ((b.proposed_monthly_pitia + b.monthly_debt_payments) / total_income) * 100
            if back_dti > 43:
                layers.append(f"High DTI ({back_dti:.1f}%)")

        # Collateral layers
        value = min(b.purchase_price, b.appraised_value) if b.loan_purpose == LoanPurpose.PURCHASE else b.appraised_value
        if value > 0:
            ltv = (b.loan_amount / value) * 100
            if ltv > 80:
                layers.append(f"High LTV ({ltv:.1f}%)")
        if b.property_type in (PropertyType.CONDO, PropertyType.MANUFACTURED, PropertyType.MULTI_2_4):
            layers.append(f"Higher-risk property type ({b.property_type.value})")
        if b.occupancy == OccupancyType.INVESTMENT:
            layers.append("Investment property")
        elif b.occupancy == OccupancyType.SECOND_HOME:
            layers.append("Second home")

        # Capital layers
        pitia = b.proposed_monthly_pitia
        if pitia > 0:
            effective_assets = b.total_liquid_assets + (b.retirement_assets * 0.6)
            reserves_after = effective_assets - b.down_payment
            months = reserves_after / pitia if pitia > 0 else 0
            if months < 2:
                layers.append(f"Low reserves ({months:.1f} months)")

        # Cash-out layer
        if b.loan_purpose == LoanPurpose.CASH_OUT_REFI:
            layers.append("Cash-out refinance")

        # Documentation layer
        if b.doc_type != IncomeDocType.FULL_DOC:
            layers.append(f"Non-full documentation ({b.doc_type.value})")

        # Self-employed layer
        if b.self_employed and b.years_self_employed < 2:
            layers.append(f"Self-employed <2 years ({b.years_self_employed} years)")

        # Assessment
        count = len(layers)
        if count <= 1:
            assessment = "Minimal risk layering — strong AUS position"
            max_layers = 4
        elif count == 2:
            assessment = "Moderate risk layering — AUS will likely still approve with compensating factors"
            max_layers = 4
        elif count == 3:
            assessment = "Significant risk layering — AUS approval becomes difficult. Address at least 1-2 layers."
            max_layers = 3
        elif count == 4:
            assessment = "Heavy risk layering — AUS will likely Refer. Must reduce risk layers before submission."
            max_layers = 3
        else:
            assessment = "Extreme risk layering — very low probability of automated approval. Major restructuring needed."
            max_layers = 2

        recommendation = (
            f"Currently {count} risk layer{'s' if count != 1 else ''}. "
            f"Target reducing to {max(0, count - 2)} layers for optimal AUS treatment. "
            f"Focus on eliminating the easiest layers first."
        )

        return LayeredRisk(
            layer_count=count,
            layers=layers,
            assessment=assessment,
            max_layers_for_approval=max_layers,
            recommendation=recommendation,
        )

    # ------------------------------------------------------------------
    # Submission strategy
    # ------------------------------------------------------------------

    def _build_submission_strategy(self, b: BorrowerProfile, eligible: list, risk: LayeredRisk) -> list:
        """Build ordered submission strategy."""
        strategy = []

        strategy.append("=" * 60)
        strategy.append("AUS SUBMISSION STRATEGY (ORDERED)")
        strategy.append("=" * 60)

        if not eligible:
            strategy.append("")
            strategy.append("WARNING: No programs currently eligible. See risk layers and")
            strategy.append("deal optimizer for restructuring recommendations.")
            return strategy

        for i, prog in enumerate(eligible, 1):
            strategy.append("")
            strategy.append(f"--- OPTION {i}: {prog.platform.value} ---")
            strategy.append(f"    Confidence: {prog.confidence}")
            strategy.append(f"    Max DTI: {prog.max_dti_allowed}% | Max LTV: {prog.max_ltv_allowed}% | Min FICO: {prog.min_credit_score}")
            if prog.estimated_rate_adjustment != 0:
                strategy.append(f"    Rate impact: {prog.estimated_rate_adjustment:+.3f}%")
            strategy.append(f"    Advantages:")
            for adv in prog.key_advantages[:3]:
                strategy.append(f"      + {adv}")
            if prog.key_risks:
                strategy.append(f"    Watch out for:")
                for risk_item in prog.key_risks[:2]:
                    strategy.append(f"      ! {risk_item}")
            strategy.append(f"    Tips:")
            for tip in prog.submission_tips[:3]:
                strategy.append(f"      > {tip}")

        strategy.append("")
        strategy.append("--- RISK LAYERING STATUS ---")
        strategy.append(f"    Active risk layers: {risk.layer_count}")
        for layer in risk.layers:
            strategy.append(f"      - {layer}")
        strategy.append(f"    Assessment: {risk.assessment}")

        return strategy

    # ------------------------------------------------------------------
    # Guideline reference
    # ------------------------------------------------------------------

    def _build_guideline_reference(self, b: BorrowerProfile) -> dict:
        """Quick reference of key guidelines relevant to this borrower."""
        ref = {}

        ref["conventional"] = {
            "min_fico": 620,
            "max_dti": "50% (DU Approve with comp factors)",
            "max_ltv_purchase_primary": "97% (Fannie 97 / HomeReady)",
            "min_reserves_primary": "0-2 months (DU determines)",
            "min_reserves_investment": "6 months PITIA",
            "bk_seasoning": "48 months (Chapter 7), 24 months (Chapter 13 discharged)",
            "fc_seasoning": "84 months",
            "max_seller_concessions": "3% (>90% LTV), 6% (75.01-90% LTV), 9% (<=75% LTV)",
        }

        ref["fha"] = {
            "min_fico": "580 (3.5% down) / 500 (10% down)",
            "max_dti": "57% with compensating factors",
            "max_ltv": "96.5%",
            "upfront_mip": "1.75%",
            "annual_mip": "0.55% (most cases)",
            "bk_seasoning": "24 months (Ch 7), 12 months into Ch 13 plan",
            "fc_seasoning": "36 months",
            "manual_uw_available": "Yes — if TOTAL Scorecard returns Refer",
        }

        ref["va"] = {
            "min_fico": "No VA minimum (lender overlays 580-620)",
            "max_dti": "No hard cap — uses residual income",
            "max_ltv": "100%",
            "funding_fee": "1.25-3.3% (first use vs subsequent, down payment dependent)",
            "pmi": "NONE",
            "bk_seasoning": "24 months",
            "fc_seasoning": "24 months",
            "residual_income": "Required — varies by region and family size",
        }

        ref["non_qm"] = {
            "min_fico": "Varies (typically 600-660)",
            "max_dti": "55% (some programs higher)",
            "programs": "Bank statement, DSCR, asset depletion, foreign national",
            "best_for": "Self-employed, investors, non-traditional income",
            "rates": "Typically 1-3% higher than conventional",
        }

        return ref
