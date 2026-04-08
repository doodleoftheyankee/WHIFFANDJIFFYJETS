# Automated Underwriting Scoring System

Analyzes loan applications the same way bank AUS platforms (Desktop Underwriter, Loan Product Advisor, FHA TOTAL) score them, then tells you exactly how to structure the deal for maximum approval probability.

## What It Does

- **Scores every factor** that AUS platforms evaluate: credit, DTI, LTV, reserves, employment, property type, occupancy, documentation
- **Shows your approval probability** and what AUS recommendation you'd likely receive (Approve/Eligible, Refer, etc.)
- **Optimizes deal structure** — runs what-if scenarios to find the fastest/cheapest path to automated approval
- **Compares all programs** — tells you whether DU, LP, FHA, or VA gives you the best shot
- **Risk layering analysis** — identifies stacked risk factors that trigger AUS downgrades
- **Action items** — specific, prioritized steps to improve your file before submission

## Quick Start

```bash
# No dependencies needed — pure Python 3
python3 main.py
```

Choose a mode:
- **Interactive** — enter borrower data and get full analysis
- **Demo** — run with sample borrower to see the system in action
- **Quick** — score-only mode (no optimization/strategy)

## Programmatic API

```python
from analyze import run_full_analysis, print_summary

result = run_full_analysis(
    credit_score=685,
    monthly_gross_income=7500,
    monthly_debt_payments=800,
    purchase_price=425000,
    down_payment=42500,
    proposed_monthly_pitia=2650,
    total_liquid_assets=65000,
    credit_utilization_pct=42,
)
print_summary(result)

# Access structured data
print(result["summary"]["recommendation"])       # "Approve/Eligible"
print(result["summary"]["approval_probability"])  # 60.8
print(result["summary"]["back_end_dti"])          # 46.0
```

## Modules

| File | Purpose |
|---|---|
| `main.py` | Interactive CLI with colored output |
| `analyze.py` | Programmatic API — import and call from scripts |
| `underwriting_engine.py` | Core scoring engine (mirrors DU/LP logic) |
| `deal_optimizer.py` | What-if scenario generator and deal restructurer |
| `aus_strategy.py` | Program comparison (DU vs LP vs FHA vs VA) and risk layering |

## Scoring Categories

The engine scores across 12 factors based on the **4 C's of Underwriting**:

**Credit** — FICO tier, credit history (lates/BK/FC), credit depth, utilization
**Capacity** — Back-end DTI ratio, employment stability
**Collateral** — LTV ratio, property type, occupancy type, loan purpose
**Capital** — Reserves (months of PITIA), documentation type

## Key Thresholds the System Tracks

| Factor | Threshold | Why It Matters |
|---|---|---|
| FICO | 740+ | Best LLPA pricing |
| FICO | 680+ | Most programs available |
| FICO | 620 | Conventional minimum |
| FICO | 580 | FHA minimum (3.5% down) |
| DTI | 43% | QM limit |
| DTI | 50% | DU/LP max with compensating factors |
| DTI | 57% | FHA max with compensating factors |
| LTV | 80% | No PMI |
| LTV | 97% | Conventional max (primary) |
| Reserves | 6+ months | Key DU compensating factor |
| Utilization | <30% | FICO scoring threshold |
| Utilization | <10% | Optimal FICO impact |
