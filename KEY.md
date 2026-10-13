# Supplier QBR Data: Key and Rules

All data is synthetic. Review quarter: **2026-Q3**. Initiative statuses are judged as of **2026-10-13**.

## Category weights (total 100%)
| Category | Weight | Metrics (each scored 1 to 5, category = simple average) |
|---|---|---|
| Delivery | 25% | On-time delivery %, in-full % |
| Quality | 20% | Defects per million (ppm), corrective-action closure days |
| Cost | 20% | Price variance % |
| Engineering | 15% | Design-change response days, design savings delivered % |
| Logistics | 10% | Lead-time adherence %, logistics savings delivered % |
| Responsiveness | 10% | Issues answered within SLA % |

## Score bands (5 = exceeds, 4 = good, 3 = meets, 2 = below expectations, 1 = poor)
Higher is better unless noted. Meeting the threshold earns the score.

| Metric | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|
| On-time delivery % | 98+ | 95+ | 90+ | 85+ | below 85 |
| In-full % | 99+ | 97+ | 94+ | 90+ | below 90 |
| Closure days (lower better) | 10 or less | 20 | 30 | 45 | over 45 |
| Price variance % (lower better) | 0 or less | 1 | 3 | 5 | over 5 |
| Design response days (lower better) | 2 or less | 4 | 7 | 10 | over 10 |
| Design savings delivered % | 100+ | 85+ | 70+ | 50+ | below 50 |
| Lead-time adherence % | 97+ | 93+ | 88+ | 80+ | below 80 |
| Logistics savings delivered % | 100+ | 85+ | 70+ | 50+ | below 50 |
| SLA answered % | 95+ | 90+ | 80+ | 70+ | below 70 |

### Defects per million (ppm): two quality classes (column `quality_class` in suppliers.csv)
| Score | PRECISION (electrical/electronic) | STANDARD (mechanical/consumer-grade) |
|---|---|---|
| 5 | 10 or less | 200 or less |
| 4 | 25 or less | 500 or less |
| 3 | 50 or less | 1,000 or less |
| 2 | 100 or less | 2,500 or less |
| 1 | over 100 | over 2,500 |

PRECISION: PCBs, circuit assemblies, wire and cable, magnetic components, sensors, semiconductors, connectors.
STANDARD: machined parts, plated metal, fasteners, box-build assemblies, packaging.
(These bands are an assumption based on general industry practice, not a published standard.)

## Flags and corrective plans
Applied to each category score and to the supplier's overall (weighted) score. **A score of 3.0 or higher gets no plan.**

| Score | Flag | Corrective plan |
|---|---|---|
| 2.0 or below | MAJOR_ISSUE | 30 days |
| above 2.0 and under 2.5 | WARNING | 60 days (30 days if under 2.1) |
| 2.5 up to under 3.0 | CAUTION | 90 days |
| 3.0 or higher | OK | none |

Note: categories average two metrics, so category scores move in steps of 0.5 (the 60-day tier can only occur on an overall score). The QBR gives full corrective plans with causes to major issues; cautions get a short monitoring plan.

## Strengths and trends
- **Strength:** category score of 4.0 or higher; the report shows at most the top 2 per supplier.
- **Trend:** compare the review quarter with last quarter (QoQ) and the same quarter last year (YoY). A change of 0.5 or more is IMPROVING or DECLINING; smaller is STABLE.

## Savings metrics and the over-delivery flag
- **Savings delivered %** = realized savings divided by savings committed to date, from initiatives with commitments. Over 100% means the supplier delivered more savings than they committed (cost came in below plan). It earns a 5.
- **over_delivery_pct** = quantity received above the quantity ordered. It is **not scored**. If it is **above 5%**, the quarter is flagged PLANNING_REVIEW so planning can decide whether to accept the extra material and protect planned inventory levels. Exactly 5.0% is not flagged.

## Initiative key
**Horizon** (when the initiative is expected to be fully delivered, from the review date): SHORT = within 6 months, MEDIUM = 6 to 18 months, LONG = over 18 months.

**Status** (checked in this order):
| Status | Criteria |
|---|---|
| NOT_STARTED | Nothing committed and no design work begun |
| IN_DESIGN | Nothing committed yet; being scoped and designed (typical for LONG) |
| DELAYED | Target completion date has passed and realized is below committed |
| AHEAD_OF_PLAN | Realized is 100% or more of committed to date |
| ON_TRACK | Realized is 75% to under 100% of committed to date (behind by 25% or less) |
| WATCH | Realized is 70% to under 75% of committed to date; monitor, no corrective plan yet |
| AT_RISK | Realized is under 70% of committed to date (behind by more than 30%); this is also a savings score below 3.0 |

**Initiative follow-ups** (dates count from the QBR date): AT_RISK or DELAYED = recovery plan due in 30 days; WATCH = status check due in 60 days. The target completion date is never used as the deadline for a recovery plan.

## Files
- `suppliers.csv`: supplier master with quality class.
- `scorecard_metrics.csv`: 8 quarters of metrics per supplier, plus `over_delivery_pct`.
- `initiatives.csv`: savings initiatives by horizon with status.
- `incidents.csv`: dated incidents and commendations. The only legitimate evidence for causes.
- `answer_key.csv`: expected category and overall results (flag, plan days, strength, trends).
- `answer_key_overdelivery.csv`: expected planning-review flags for the review quarter.
