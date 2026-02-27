"""
Deal Structure Optimizer
========================
Takes a borrower profile and systematically tests different deal structures
to find the optimal path to AUS approval. Simulates what-if scenarios and
ranks strategies by impact and feasibility.
"""

from dataclasses import dataclass
from typing import Optional
from underwriting_engine import (
    BorrowerProfile, UnderwritingEngine, UnderwritingResult,
    AUSRecommendation, LoanPurpose, OccupancyType, IncomeDocType,
)
import copy


@dataclass
class Scenario:
    """A what-if scenario with projected outcome."""
    name: str
    description: str
    changes: dict  # field -> new value
    difficulty: str  # "Easy", "Moderate", "Hard", "Very Hard"
    timeframe: str  # "Immediate", "1-2 weeks", "1-3 months", "3-6 months", "6-12 months"
    estimated_cost: float  # dollar cost to implement
    result: Optional[UnderwritingResult] = None
    score_improvement: float = 0.0
    approval_prob_improvement: float = 0.0
    new_recommendation: Optional[AUSRecommendation] = None


class DealOptimizer:
    """
    Generates and ranks deal restructuring scenarios to maximize
    AUS approval probability.
    """

    def __init__(self):
        self.engine = UnderwritingEngine()

    def optimize(self, borrower: BorrowerProfile) -> dict:
        """
        Run full optimization analysis.
        Returns dict with baseline, scenarios, and ranked recommendations.
        """
        # 1. Get baseline
        baseline = self.engine.analyze(borrower)

        # 2. Generate all possible scenarios
        scenarios = []
        scenarios.extend(self._credit_scenarios(borrower, baseline))
        scenarios.extend(self._dti_scenarios(borrower, baseline))
        scenarios.extend(self._ltv_scenarios(borrower, baseline))
        scenarios.extend(self._reserves_scenarios(borrower, baseline))
        scenarios.extend(self._program_switch_scenarios(borrower, baseline))
        scenarios.extend(self._combined_scenarios(borrower, baseline))

        # 3. Score each scenario
        scored = []
        for scenario in scenarios:
            modified = copy.deepcopy(borrower)
            for field_name, value in scenario.changes.items():
                setattr(modified, field_name, value)
            # Recalculate derived fields
            modified.__post_init__()
            result = self.engine.analyze(modified)
            scenario.result = result
            scenario.score_improvement = result.score_pct - baseline.score_pct
            scenario.approval_prob_improvement = result.approval_probability_pct - baseline.approval_probability_pct
            scenario.new_recommendation = result.recommendation
            scored.append(scenario)

        # 4. Rank by approval probability improvement
        scored.sort(key=lambda s: s.approval_prob_improvement, reverse=True)

        # 5. Find the best achievable path
        quick_wins = [s for s in scored if s.timeframe in ("Immediate", "1-2 weeks") and s.approval_prob_improvement > 0]
        medium_term = [s for s in scored if s.timeframe in ("1-3 months",) and s.approval_prob_improvement > 0]
        long_term = [s for s in scored if s.timeframe in ("3-6 months", "6-12 months") and s.approval_prob_improvement > 0]

        # Find minimum changes needed for Approve/Eligible
        approval_path = self._find_approval_path(scored, baseline)

        return {
            "baseline": baseline,
            "all_scenarios": scored,
            "quick_wins": quick_wins[:5],
            "medium_term": medium_term[:5],
            "long_term": long_term[:5],
            "approval_path": approval_path,
            "best_scenario": scored[0] if scored else None,
        }

    # ------------------------------------------------------------------
    # Scenario generators
    # ------------------------------------------------------------------

    def _credit_scenarios(self, b: BorrowerProfile, baseline: UnderwritingResult) -> list:
        scenarios = []

        # Pay down utilization
        if b.credit_utilization_pct > 30:
            for target_util in [30, 20, 10, 5]:
                if target_util < b.credit_utilization_pct:
                    # Estimate FICO boost from utilization reduction
                    fico_boost = int((b.credit_utilization_pct - target_util) * 0.7)
                    new_score = min(850, b.credit_score + fico_boost)
                    # Estimate cost (rough: assume revolving balance reduction)
                    est_balance_reduction = b.monthly_debt_payments * 15 * ((b.credit_utilization_pct - target_util) / 100)
                    scenarios.append(Scenario(
                        name=f"Reduce utilization to {target_util}%",
                        description=f"Pay down revolving balances to {target_util}% utilization. "
                                    f"Estimated FICO boost: +{fico_boost} pts -> {new_score}",
                        changes={
                            "credit_utilization_pct": target_util,
                            "credit_score": new_score,
                        },
                        difficulty="Easy" if est_balance_reduction < 5000 else "Moderate",
                        timeframe="Immediate" if est_balance_reduction < 5000 else "1-2 weeks",
                        estimated_cost=est_balance_reduction,
                    ))

        # Add authorized user tradeline
        if b.number_of_tradelines < 5 or b.oldest_tradeline_months < 60:
            fico_boost = 15 if b.number_of_tradelines < 3 else 8
            scenarios.append(Scenario(
                name="Add authorized user tradeline",
                description=f"Get added as authorized user on seasoned account. "
                            f"Estimated FICO boost: +{fico_boost} pts",
                changes={
                    "credit_score": min(850, b.credit_score + fico_boost),
                    "number_of_tradelines": b.number_of_tradelines + 1,
                    "oldest_tradeline_months": max(b.oldest_tradeline_months, 60),
                },
                difficulty="Easy",
                timeframe="1-2 weeks",
                estimated_cost=0,
            ))

        # Wait for derogatory aging
        if b.late_payments_12mo > 0:
            scenarios.append(Scenario(
                name="Wait for 12-month clean history",
                description="Allow 12 months of perfect payment history to pass. "
                            "Lates fall off recent history window.",
                changes={
                    "late_payments_12mo": 0,
                    "late_payments_24mo": b.late_payments_12mo + b.late_payments_24mo,
                    "credit_score": min(850, b.credit_score + 30),
                },
                difficulty="Easy",
                timeframe="6-12 months",
                estimated_cost=0,
            ))

        # Rapid rescore
        if b.credit_utilization_pct > 30 or b.credit_score < 740:
            scenarios.append(Scenario(
                name="Rapid rescore (pay + rescore in 3-5 days)",
                description="Pay down cards, then have LO submit rapid rescore to bureaus. "
                            "Reflects new balances in 3-5 business days instead of waiting for statement cycle.",
                changes={
                    "credit_utilization_pct": min(b.credit_utilization_pct, 10),
                    "credit_score": min(850, b.credit_score + int((b.credit_utilization_pct - 10) * 0.7) if b.credit_utilization_pct > 10 else b.credit_score),
                },
                difficulty="Moderate",
                timeframe="1-2 weeks",
                estimated_cost=50,  # rapid rescore fee per account
            ))

        return scenarios

    def _dti_scenarios(self, b: BorrowerProfile, baseline: UnderwritingResult) -> list:
        scenarios = []
        total_income = b.monthly_gross_income + b.co_borrower_monthly_income
        if total_income == 0:
            return scenarios

        # Pay off specific debt tiers
        current_back_dti = baseline.back_end_dti
        if current_back_dti > 43:
            # Calculate what debt reduction gets us to each threshold
            for target_dti, label in [(43, "QM limit"), (40, "Strong"), (36, "Ideal")]:
                target_total_debt = total_income * (target_dti / 100)
                current_total_debt = b.proposed_monthly_pitia + b.monthly_debt_payments
                reduction = current_total_debt - target_total_debt
                if reduction > 0:
                    payoff_amount = reduction * 25  # approximate balance to eliminate
                    new_monthly_debts = max(0, b.monthly_debt_payments - reduction)
                    scenarios.append(Scenario(
                        name=f"Reduce DTI to {target_dti}% ({label})",
                        description=f"Pay off ${payoff_amount:,.0f} in debts to reduce monthly "
                                    f"payments by ${reduction:,.0f}/mo",
                        changes={"monthly_debt_payments": new_monthly_debts},
                        difficulty="Moderate" if payoff_amount < 10000 else "Hard",
                        timeframe="Immediate" if payoff_amount < 5000 else "1-3 months",
                        estimated_cost=payoff_amount,
                    ))

        # Add co-borrower income
        if b.co_borrower_monthly_income == 0 and current_back_dti > 43:
            needed_income = (b.proposed_monthly_pitia + b.monthly_debt_payments) / 0.43 - total_income
            scenarios.append(Scenario(
                name="Add co-borrower/non-occupant co-signer",
                description=f"Adding ${needed_income:,.0f}/mo co-borrower income brings DTI to 43%. "
                            f"Non-occupant co-signers allowed on FHA/conventional.",
                changes={"co_borrower_monthly_income": needed_income},
                difficulty="Moderate",
                timeframe="1-2 weeks",
                estimated_cost=0,
            ))

        # Buy down rate to reduce PITIA
        if b.proposed_monthly_pitia > 0:
            # Rough estimate: 1 point buydown reduces payment ~$60/$100k loan
            for points_cost, payment_reduction_pct in [(1, 0.04), (2, 0.07), (3, 0.10)]:
                reduced_pitia = b.proposed_monthly_pitia * (1 - payment_reduction_pct)
                cost = b.loan_amount * (points_cost / 100)
                scenarios.append(Scenario(
                    name=f"Buy down rate ({points_cost} point{'s' if points_cost > 1 else ''})",
                    description=f"Pay ${cost:,.0f} in discount points to reduce monthly PITIA "
                                f"by ${b.proposed_monthly_pitia - reduced_pitia:,.0f}/mo",
                    changes={"proposed_monthly_pitia": reduced_pitia},
                    difficulty="Moderate",
                    timeframe="Immediate",
                    estimated_cost=cost,
                ))

        return scenarios

    def _ltv_scenarios(self, b: BorrowerProfile, baseline: UnderwritingResult) -> list:
        scenarios = []
        if b.loan_amount == 0 or b.appraised_value == 0:
            return scenarios

        current_ltv = baseline.ltv

        # Increase down payment to hit key LTV thresholds
        for target_ltv, label in [(95, "95% LTV"), (90, "90% LTV"), (85, "85% LTV"),
                                   (80, "80% LTV - No PMI"), (75, "75% LTV - Best pricing")]:
            if current_ltv > target_ltv:
                value = min(b.purchase_price, b.appraised_value) if b.purchase_price > 0 else b.appraised_value
                target_loan = value * (target_ltv / 100)
                additional_down = b.loan_amount - target_loan
                if additional_down > 0:
                    # Recalculate PITIA roughly (proportional reduction)
                    pitia_ratio = target_loan / b.loan_amount
                    new_pitia = b.proposed_monthly_pitia * pitia_ratio
                    # Remove PMI estimate if going below 80%
                    if target_ltv <= 80 and current_ltv > 80:
                        pmi_estimate = b.loan_amount * 0.005 / 12  # rough PMI estimate
                        new_pitia -= pmi_estimate

                    scenarios.append(Scenario(
                        name=f"Increase down payment to {label}",
                        description=f"Add ${additional_down:,.0f} to down payment. "
                                    f"{'Eliminates PMI. ' if target_ltv <= 80 and current_ltv > 80 else ''}"
                                    f"New loan amount: ${target_loan:,.0f}",
                        changes={
                            "down_payment": b.down_payment + additional_down,
                            "loan_amount": target_loan,
                            "proposed_monthly_pitia": new_pitia,
                        },
                        difficulty="Hard" if additional_down > 20000 else "Moderate",
                        timeframe="1-3 months" if additional_down > 10000 else "1-2 weeks",
                        estimated_cost=additional_down,
                    ))

        # Gift funds for down payment
        if current_ltv > 80:
            value = min(b.purchase_price, b.appraised_value) if b.purchase_price > 0 else b.appraised_value
            target_loan = value * 0.80
            gift_needed = b.loan_amount - target_loan
            if gift_needed > 0:
                new_pitia = b.proposed_monthly_pitia * (target_loan / b.loan_amount)
                pmi_estimate = b.loan_amount * 0.005 / 12
                new_pitia -= pmi_estimate
                scenarios.append(Scenario(
                    name="Gift funds to reach 80% LTV",
                    description=f"Receive ${gift_needed:,.0f} gift from family. Need gift letter, "
                                f"donor bank statements. Eliminates PMI.",
                    changes={
                        "down_payment": b.down_payment + gift_needed,
                        "loan_amount": target_loan,
                        "proposed_monthly_pitia": new_pitia,
                    },
                    difficulty="Moderate",
                    timeframe="1-2 weeks",
                    estimated_cost=0,
                ))

        # Seller concessions
        if b.loan_purpose == LoanPurpose.PURCHASE:
            max_concession_pct = 3 if current_ltv > 90 else 6 if current_ltv > 75 else 9
            concession = min(b.purchase_price * (max_concession_pct / 100), b.loan_amount * 0.03)
            scenarios.append(Scenario(
                name=f"Negotiate seller concessions ({max_concession_pct}% max)",
                description=f"Seller pays up to ${concession:,.0f} toward closing costs/buydown. "
                            f"Frees up cash for reserves or debt payoff.",
                changes={
                    "total_liquid_assets": b.total_liquid_assets + concession,
                },
                difficulty="Moderate",
                timeframe="Immediate",
                estimated_cost=0,
            ))

        return scenarios

    def _reserves_scenarios(self, b: BorrowerProfile, baseline: UnderwritingResult) -> list:
        scenarios = []
        pitia = b.proposed_monthly_pitia
        if pitia == 0:
            return scenarios

        current_reserves = baseline.factors[6].value if len(baseline.factors) > 6 else "0"

        # Build reserves to key thresholds
        for target_months in [2, 6, 12]:
            target_assets = target_months * pitia + b.down_payment
            additional_needed = target_assets - (b.total_liquid_assets + b.retirement_assets * 0.6)
            if additional_needed > 0:
                scenarios.append(Scenario(
                    name=f"Build reserves to {target_months} months",
                    description=f"Accumulate ${additional_needed:,.0f} in liquid assets. "
                                f"{'This triggers DU compensating factor credit.' if target_months >= 6 else ''}",
                    changes={
                        "total_liquid_assets": b.total_liquid_assets + additional_needed,
                        "months_reserves": target_months,
                    },
                    difficulty="Moderate" if additional_needed < 10000 else "Hard",
                    timeframe="1-3 months" if additional_needed < 10000 else "3-6 months",
                    estimated_cost=additional_needed,
                ))

        # 401k as reserves (counted at 60%)
        if b.retirement_assets == 0:
            scenarios.append(Scenario(
                name="Document retirement accounts for reserves",
                description="Retirement accounts (401k, IRA) are counted at 60% of vested balance "
                            "for reserves. Provide most recent statement.",
                changes={"retirement_assets": pitia * 10},  # assume $10 months worth exists
                difficulty="Easy",
                timeframe="Immediate",
                estimated_cost=0,
            ))

        return scenarios

    def _program_switch_scenarios(self, b: BorrowerProfile, baseline: UnderwritingResult) -> list:
        scenarios = []

        # FHA option
        if b.credit_score >= 580 and b.doc_type == IncomeDocType.FULL_DOC:
            fha_loan = b.loan_amount
            upfront_mip = fha_loan * 0.0175
            annual_mip = fha_loan * 0.0085 / 12  # approximate
            new_pitia = b.proposed_monthly_pitia + annual_mip  # rough addition
            scenarios.append(Scenario(
                name="Switch to FHA program",
                description=f"FHA allows 580+ FICO, up to 57% DTI with compensating factors, "
                            f"3.5% min down. MIP cost: ${upfront_mip:,.0f} upfront + ${annual_mip:,.0f}/mo",
                changes={
                    "proposed_monthly_pitia": new_pitia,
                },
                difficulty="Easy",
                timeframe="Immediate",
                estimated_cost=upfront_mip,
            ))

        # VA option (always suggest checking)
        scenarios.append(Scenario(
            name="Check VA eligibility",
            description="VA loans: 0% down, no PMI, no hard FICO floor (most lenders 580-620), "
                        "residual income model instead of strict DTI. Best deal if eligible.",
            changes={
                "down_payment": 0,
                "loan_amount": b.purchase_price if b.purchase_price > 0 else b.loan_amount,
            },
            difficulty="Easy",
            timeframe="1-2 weeks",
            estimated_cost=0,
        ))

        # Bank statement program for self-employed
        if b.self_employed and b.doc_type == IncomeDocType.FULL_DOC:
            scenarios.append(Scenario(
                name="Switch to bank statement program",
                description="Use 12-24 month bank statement deposits instead of tax returns. "
                            "Often shows higher qualifying income for self-employed borrowers.",
                changes={"doc_type": IncomeDocType.BANK_STATEMENTS},
                difficulty="Easy",
                timeframe="1-2 weeks",
                estimated_cost=0,
            ))

        # DSCR for investment property
        if b.occupancy == OccupancyType.INVESTMENT and b.monthly_rental_income > 0:
            scenarios.append(Scenario(
                name="Switch to DSCR loan (investment)",
                description=f"DSCR loan qualifies on property cash flow only — no personal income docs. "
                            f"Rental ${b.monthly_rental_income:,.0f}/mo vs PITIA ${b.proposed_monthly_pitia:,.0f}/mo. "
                            f"DSCR ratio: {b.monthly_rental_income / b.proposed_monthly_pitia:.2f}x" if b.proposed_monthly_pitia > 0 else "N/A",
                changes={"doc_type": IncomeDocType.DSCR},
                difficulty="Easy",
                timeframe="1-2 weeks",
                estimated_cost=0,
            ))

        return scenarios

    def _combined_scenarios(self, b: BorrowerProfile, baseline: UnderwritingResult) -> list:
        """Generate combined high-impact scenarios."""
        scenarios = []

        # Combined: pay down utilization + pay off small debts
        if b.credit_utilization_pct > 30 and baseline.back_end_dti > 43:
            fico_boost = int((b.credit_utilization_pct - 10) * 0.7)
            new_score = min(850, b.credit_score + fico_boost)
            total_income = b.monthly_gross_income + b.co_borrower_monthly_income
            target_debt = total_income * 0.43
            current_debt = b.proposed_monthly_pitia + b.monthly_debt_payments
            reduction = max(0, current_debt - target_debt)
            new_monthly_debts = max(0, b.monthly_debt_payments - reduction)
            cost = reduction * 25 + b.monthly_debt_payments * 10

            scenarios.append(Scenario(
                name="COMBO: Pay down cards + pay off debts",
                description=f"Pay down utilization to 10% AND pay off debts to hit 43% DTI. "
                            f"Estimated FICO boost: +{fico_boost} pts. New DTI: ~43%.",
                changes={
                    "credit_utilization_pct": 10,
                    "credit_score": new_score,
                    "monthly_debt_payments": new_monthly_debts,
                },
                difficulty="Hard",
                timeframe="1-3 months",
                estimated_cost=cost,
            ))

        # Combined: increase down payment + build reserves
        if baseline.ltv > 80:
            value = min(b.purchase_price, b.appraised_value) if b.purchase_price > 0 else b.appraised_value
            target_loan = value * 0.80
            additional_down = b.loan_amount - target_loan
            new_pitia = b.proposed_monthly_pitia * (target_loan / b.loan_amount)
            reserve_target = new_pitia * 6 + (b.down_payment + additional_down)
            additional_reserves = max(0, reserve_target - (b.total_liquid_assets + b.retirement_assets * 0.6))

            scenarios.append(Scenario(
                name="COMBO: 80% LTV + 6 months reserves",
                description=f"Increase down payment by ${additional_down:,.0f} (no PMI) "
                            f"and build reserves to 6 months. Maximum AUS impact.",
                changes={
                    "down_payment": b.down_payment + additional_down,
                    "loan_amount": target_loan,
                    "proposed_monthly_pitia": new_pitia,
                    "months_reserves": 6,
                    "total_liquid_assets": b.total_liquid_assets + additional_down + additional_reserves,
                },
                difficulty="Very Hard",
                timeframe="3-6 months",
                estimated_cost=additional_down + additional_reserves,
            ))

        return scenarios

    def _find_approval_path(self, scored_scenarios: list, baseline: UnderwritingResult) -> list:
        """Find the minimum set of changes needed to reach Approve/Eligible."""
        if baseline.recommendation == AUSRecommendation.APPROVE_ELIGIBLE:
            return [{"message": "Already at Approve/Eligible! Focus on optimizing pricing (LLPA reduction)."}]

        # Find single scenarios that achieve approval
        single_approvals = [
            s for s in scored_scenarios
            if s.new_recommendation == AUSRecommendation.APPROVE_ELIGIBLE
        ]

        if single_approvals:
            # Sort by cost
            single_approvals.sort(key=lambda s: s.estimated_cost)
            cheapest = single_approvals[0]
            fastest_time_order = {"Immediate": 0, "1-2 weeks": 1, "1-3 months": 2, "3-6 months": 3, "6-12 months": 4}
            single_approvals.sort(key=lambda s: fastest_time_order.get(s.timeframe, 5))
            fastest = single_approvals[0]

            path = []
            path.append({
                "strategy": "Cheapest path to approval",
                "scenario": cheapest.name,
                "cost": cheapest.estimated_cost,
                "timeframe": cheapest.timeframe,
                "description": cheapest.description,
            })
            if fastest.name != cheapest.name:
                path.append({
                    "strategy": "Fastest path to approval",
                    "scenario": fastest.name,
                    "cost": fastest.estimated_cost,
                    "timeframe": fastest.timeframe,
                    "description": fastest.description,
                })
            return path

        return [{"message": "No single change achieves Approve/Eligible. "
                            "Combine multiple strategies from the recommendations above."}]
