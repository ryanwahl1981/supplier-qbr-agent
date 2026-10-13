# Supplier Performance + Procurement QBR Agent

An AI agent that turns supplier scorecard data into a **Quarterly Business Review (QBR)** for each supplier: weighted scores, quarter-over-quarter and year-over-year trends, major issues with corrective action plans, strengths, an engineering and logistics savings pipeline, and a risk outlook.

**The design rule:** code decides every number; the AI investigates and writes; code checks the writing.

- **Code decides** scores, flags, trends, plan lengths and due dates, strengths, initiative statuses and the over-delivery flag (`scorecard.py`).
- **Claude investigates and writes** the narrative: what happened, likely cause (only from the incident log), corrective actions, asks of the supplier (`agent.py`).
- **Code checks the writing** (`qbr_checks.py`): the right issues are covered, every number, date and ID comes from the data, causes cite real incidents, and initiative statuses match the rules. A QBR that fails is sent back once with exact fixes; if it still fails it is flagged for human review.

Built by a supply chain and procurement professional (not a software engineer) as the third project in an AI-agent portfolio, after the [Master Data Quality Agent](https://github.com/ryanwahl1981/master-data-quality-agent) and the [Supply Chain Risk Detection Agent](https://github.com/ryanwahl1981/supply-chain-risk-agent). All data is **synthetic**.

## What a QBR contains

1. Executive summary
2. Scorecard table (6 weighted categories) with trend vs last quarter and vs the same quarter last year
3. **Major issues** (score 2.0 or below), each with evidence, likely cause, a corrective action plan with due date and checkpoints, and what the supplier must commit to
4. Caution items (score 2.5 to under 3.0) with a monitoring plan
5. 1 or 2 **strengths** (score 4.0 or higher)
6. Engineering and logistics **savings pipeline** by SHORT / MEDIUM / LONG horizon, plus a table of initiatives needing follow-up
7. A **planning review** flag if a supplier shipped more than 5% above the ordered quantity
8. Asks of the supplier
9. Risk outlook, linked to the Risk Detection Agent's results for the same supplier

Sample output: [`example_output/QBR_SUP-004.md`](example_output/QBR_SUP-004.md), [`example_output/QBR_SUP-005.md`](example_output/QBR_SUP-005.md) and [`example_output/qbr_summary.md`](example_output/qbr_summary.md).

## The scorecard rules (full detail in [`KEY.md`](KEY.md))

| Category | Weight | Metrics (each scored 1 to 5) |
|---|---|---|
| Delivery | 25% | On-time delivery, in-full |
| Quality | 20% | Defects per million (ppm), corrective-action closure days |
| Cost | 20% | Price variance |
| Engineering | 15% | Design-change response days, design savings delivered |
| Logistics | 10% | Lead-time adherence, logistics savings delivered |
| Responsiveness | 10% | Issues answered within SLA |

- **Flags and corrective plans:** score 2.0 or below = major issue, 30-day plan. Above 2.0 and under 2.5 = warning, 60-day plan. 2.5 up to under 3.0 = caution, 90-day plan. 3.0 or higher = no plan.
- **Trend:** a change of 0.5 or more is improving or declining.
- **Defects per million:** two band sets, a tight one for precision/electrical parts (semiconductors, circuits, sensors, connectors) and a looser one for standard mechanical and consumer-grade parts.
- **Savings initiatives:** status is calculated from realized vs committed savings: ahead of plan (100%+), on track (75% to under 100%), watch (70% to under 75%), at risk (under 70%), delayed (target date passed and below committed). Savings over 100% of committed earn full credit.
- **Over-delivery:** quantity received more than 5% above the order is flagged for planning to decide whether to accept the extra material (it is not scored).

Every threshold is a setting at the top of `scorecard.py`, so the rules can be changed to fit a different business.

## Measured results

The agent was run on 12 synthetic suppliers with a hand-written answer key (planted major issues, a caution, strengths, trend changes, an over-delivery case, and "decoy" suppliers that should NOT be flagged, including one sitting exactly on the 5.0% over-delivery boundary). Model: `claude-haiku-4-5`.

| Check | Result |
|---|---|
| Scorecard values vs answer key (scores, flags, plan days, strengths, trends) | 588 / 588 |
| Initiative statuses recalculated from the savings numbers | 60 / 60 |
| Over-delivery flags (including the 5.0% boundary decoy) | 12 / 12 |
| QBRs written | 12 / 12 |
| Major issues exactly match the key | 12 / 12 |
| Caution items exactly match | 12 / 12 |
| Strengths exactly match | 12 / 12 |
| Causes cite real incidents of the right supplier and category | 12 / 12 |
| Initiative statuses described correctly | 12 / 12 |
| Over-delivery raised only when flagged | 12 / 12 |
| Every number and ID in the narrative appears in the data | 12 / 12 |
| Tone, length (slide-ready word limits), summary and detail | 12 / 12 |

- **Retries:** 6 of 12 QBRs failed a check on the first try and passed after one revision. Across three full runs during development this was 10, 9, then 6 of 12.
- **Cost:** about **$0.24** for all 12 QBRs (roughly 2 cents each) at the time of the run.
- **Run it free first:** `test_offline.py` runs the whole agent loop with a stand-in for Claude, including deliberate mistakes, so the checks and retry can be tested without spending anything.

**How to read these numbers:** this is a *development score*. The same dataset was used to tune the prompts and checks, so a fresh dataset would likely score lower. Part A tests the rules engine against the answer key; Part B grades the agent's writing against the same key.

## What went wrong along the way (and how it was fixed)

- The first QBRs invented dates for follow-up asks, so initiative follow-up dates became a rule decided by code and the numbers check now catches any date or figure not in the data.
- Claude guessed causes that the incident log did not state ("review cycles", "capacity"), so the prompt now restricts causes to the incident record and requires "cause not confirmed" when there is none.
- A missing section crashed a full run. The agent now validates the shape of every submission and one bad QBR no longer stops the others.
- Several checks were really formatting jobs (printing scores, follow-up tables), so code now builds those and Claude only writes the explanation. That cut retries.

## Limitations (please read)

- **Synthetic data, one quarter, 12 suppliers.** Real data is messier.
- **The checks verify facts, not meaning.** They confirm numbers, dates, IDs, structure and statuses, but they cannot judge whether a sentence makes sense. Slips seen in the final run: "declines across both metrics" for a category with one metric; some dollar amounts without commas; a horizon described as "on track" next to an at-risk initiative. A buyer must still review every QBR.
- **Causes are only as good as the incident log.** The agent never verifies an incident.
- **Risk outlook is a snapshot.** It uses the Risk Detection Agent's results as of 2026-10-02 and says so.
- **Thresholds and bands are assumptions** (the defects-per-million bands are based on general industry practice, not a published standard). Change them in `scorecard.py`.
- **A small, cheap model is used.** Wording and retry counts vary from run to run.
- The agent only drafts. It never changes data or contacts a supplier.

## How to run it (Windows)

1. Install Python and put these files in one folder, for example `C:\Users\<you>\qbr_agent`.
2. Open Command Prompt in that folder and run: `pip install -r requirements.txt`
3. Set your Anthropic API key once: `setx ANTHROPIC_API_KEY "your-key-here"` (then close and reopen Command Prompt). **Never put the key in a file.**
4. See the scores (no AI, free): `python scorecard.py`
5. Test the agent loop (free): `python test_offline.py`
6. Draft the QBRs: `python agent.py` (set `MAX_SUPPLIERS` or `ONLY_SUPPLIERS` at the top of `agent.py`)
7. Score the result: `python evaluate.py`

## Files

| File | What it is |
|---|---|
| `scorecard.py` | Rules engine: scores, flags, plans, trends, strengths, statuses, over-delivery flag |
| `qbr_checks.py` | The "must mention" list and the wording checks |
| `agent.py` | The Claude agent: tools, retry, QBR and summary output |
| `evaluate.py` | Grades the engine and the QBRs against the hand-written answer key |
| `test_offline.py` | Free test of the full loop with a stand-in for Claude |
| `KEY.md` | Data dictionary and every rule |
| `suppliers.csv`, `scorecard_metrics.csv`, `initiatives.csv`, `incidents.csv` | Synthetic input data |
| `supplier_tiers.csv`, `risk_assessment.csv` | Results from the Risk Detection Agent (optional link) |
| `answer_key.csv`, `answer_key_overdelivery.csv` | Hand-written expected results |
| `example_output/` | Sample QBRs and summary |

## About

Built by **Ryan Wahl**, supply chain, procurement and data governance professional. [LinkedIn](https://www.linkedin.com/in/ryanmwahl)
