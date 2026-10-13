"""
Scorecard rules engine (no AI in this file).

This is where every number in the QBR is decided: metric scores, category scores,
flags, corrective-plan lengths and due dates, strengths, trends, savings pipeline,
initiative statuses and the over-delivery flag. The AI agent (agent.py) only reads
these results and writes the explanation. The rules are documented in KEY.md.

Run it on its own:   python scorecard.py
It writes scorecard_results.csv and initiative_status.csv so you can check the rules by eye.
"""
import datetime as dt

import pandas as pd

# ------------------------------------------------------------------
# SETTINGS: change a rule here and re-run
# ------------------------------------------------------------------
AS_OF = dt.date(2026, 10, 13)         # QBR date: corrective plans start today
TREND_THRESHOLD = 0.5                 # change in category score that counts as IMPROVING / DECLINING
MAJOR_MAX = 2.0                       # score at or below this is a MAJOR_ISSUE (30-day plan)
WARNING_MAX = 2.5                     # above 2.0 and below 2.5 is a WARNING (60-day plan)
OK_MIN = 3.0                          # 3.0 or higher is OK, no plan. 2.5 up to 3.0 is CAUTION (90-day plan)
STRENGTH_MIN = 4.0                    # category score at or above this is a strength (top 2 are shown)
OVER_DELIVERY_LIMIT = 5.0             # quantity received more than this % above the order -> planning review

WEIGHTS = {"Delivery": 0.25, "Quality": 0.20, "Cost": 0.20, "Engineering": 0.15, "Logistics": 0.10, "Responsiveness": 0.10}
CATEGORY_METRICS = {"Delivery": ["otd", "in_full"], "Quality": ["ppm", "closure"], "Cost": ["price"],
                    "Engineering": ["dresp", "dsav"], "Logistics": ["lt", "lsav"], "Responsiveness": ["sla"]}
COLUMN = {"otd": "otd_pct", "in_full": "in_full_pct", "ppm": "defects_ppm", "closure": "corrective_action_closure_days",
          "price": "price_variance_pct", "dresp": "design_change_response_days", "dsav": "design_savings_delivered_pct",
          "lt": "lead_time_adherence_pct", "lsav": "logistics_savings_delivered_pct", "sla": "issues_answered_within_sla_pct"}
LABEL = {"otd": "On-time delivery %", "in_full": "In-full %", "ppm": "Defects per million", "closure": "Corrective-action closure days",
         "price": "Price variance %", "dresp": "Design-change response days", "dsav": "Design savings delivered %",
         "lt": "Lead-time adherence %", "lsav": "Logistics savings delivered %", "sla": "Issues answered within SLA %"}
# direction, thresholds that earn a 5, 4, 3, 2 (anything worse scores 1)
BANDS = {"otd": ("higher", [98, 95, 90, 85]), "in_full": ("higher", [99, 97, 94, 90]), "closure": ("lower", [10, 20, 30, 45]),
         "price": ("lower", [0, 1, 3, 5]), "dresp": ("lower", [2, 4, 7, 10]), "dsav": ("higher", [100, 85, 70, 50]),
         "lt": ("higher", [97, 93, 88, 80]), "lsav": ("higher", [100, 85, 70, 50]), "sla": ("higher", [95, 90, 80, 70])}
PPM_BANDS = {"PRECISION": [10, 25, 50, 100], "STANDARD": [200, 500, 1000, 2500]}   # by supplier quality_class
HORIZONS = ["SHORT", "MEDIUM", "LONG"]
# follow-up the supplier owes on a flagged initiative: (what, days from the QBR date)
INITIATIVE_FOLLOW_UP = {"AT_RISK": ("recovery plan", 30), "DELAYED": ("recovery plan", 30), "WATCH": ("status check", 60)}


# ------------------------------------------------------------------
# Rules
# ------------------------------------------------------------------
def band(metric, quality_class):
    if metric == "ppm":
        return "lower", PPM_BANDS[quality_class]
    return BANDS[metric]


def metric_score(metric, value, quality_class):
    direction, thresholds = band(metric, quality_class)
    for points, t in zip([5, 4, 3, 2], thresholds):
        if (value >= t) if direction == "higher" else (value <= t):
            return points
    return 1


def flag_of(score):
    s = round(score, 2)
    if s <= MAJOR_MAX:
        return "MAJOR_ISSUE"
    if s < WARNING_MAX:
        return "WARNING"
    if s < OK_MIN:
        return "CAUTION"
    return "OK"


def plan_days_of(score):
    s = round(score, 2)
    if s < 2.1:
        return 30
    if s < WARNING_MAX:
        return 60
    if s < OK_MIN:
        return 90
    return None


def make_plan(days):
    if days is None:
        return None
    step_days = [15, 30] if days == 30 else list(range(30, days + 1, 30))
    return {"days": days, "start_date": AS_OF.isoformat(), "due_date": (AS_OF + dt.timedelta(days=days)).isoformat(),
            "checkpoint_dates": [(AS_OF + dt.timedelta(days=d)).isoformat() for d in step_days],
            "goal": "category score back to 3.0 or higher"}


def trend_label(delta):
    return "IMPROVING" if delta >= TREND_THRESHOLD else "DECLINING" if delta <= -TREND_THRESHOLD else "STABLE"


def initiative_status(row):
    """Checked in this order (see KEY.md)."""
    committed, realized = row["committed_to_date_usd"], row["realized_to_date_usd"]
    if committed == 0:
        return None          # NOT_STARTED vs IN_DESIGN is design-work status, taken from the file
    ratio = realized / committed
    if ratio < 1.0 and str(row["target_completion_date"]) < AS_OF.isoformat():
        return "DELAYED"
    if ratio >= 1.0:
        return "AHEAD_OF_PLAN"
    if ratio >= 0.75:
        return "ON_TRACK"
    if ratio >= 0.70:
        return "WATCH"
    return "AT_RISK"


# ------------------------------------------------------------------
# Data
# ------------------------------------------------------------------
def read_data(folder="."):
    d = {n: pd.read_csv(f"{folder}/{n}.csv") for n in ["suppliers", "scorecard_metrics", "initiatives", "incidents"]}
    return d


def category_scores(metrics_row, quality_class):
    out = {}
    for cat, ms in CATEGORY_METRICS.items():
        out[cat] = sum(metric_score(m, metrics_row[COLUMN[m]], quality_class) for m in ms) / len(ms)
    return out


def build_scorecards(data):
    """Returns {supplier_id: scorecard dict} for the latest quarter in the data."""
    sup = data["suppliers"].set_index("supplier_id")
    met = data["scorecard_metrics"]
    quarters = sorted(met.quarter.unique())
    cur_q, qoq_q, yoy_q = quarters[-1], quarters[-2], quarters[-5]
    ini = data["initiatives"].copy()
    ini["status"] = [initiative_status(r) or r["status"] for _, r in ini.iterrows()]
    cards = {}
    for sid in sup.index:
        s = sup.loc[sid]
        qc = s.quality_class
        rows = met[met.supplier_id == sid].set_index("quarter")
        cur, prev, year = category_scores(rows.loc[cur_q], qc), category_scores(rows.loc[qoq_q], qc), category_scores(rows.loc[yoy_q], qc)
        overall = round(sum(WEIGHTS[c] * cur[c] for c in cur), 2)
        eligible = sorted([c for c in cur if cur[c] >= STRENGTH_MIN], key=lambda c: (-cur[c], -WEIGHTS[c]))[:2]
        cats = {}
        for cat, ms in CATEGORY_METRICS.items():
            metrics = []
            for m in ms:
                direction, th = band(m, qc)
                metrics.append({"metric": LABEL[m], "value": float(rows.loc[cur_q, COLUMN[m]]), "score": metric_score(m, rows.loc[cur_q, COLUMN[m]], qc),
                                "better_when": direction, "value_needed_for_a_3": th[2],
                                "history": {q: float(rows.loc[q, COLUMN[m]]) for q in quarters}})
            sc = cur[cat]
            cats[cat] = {"score": round(sc, 1), "weight_pct": round(WEIGHTS[cat] * 100), "flag": flag_of(sc), "plan": make_plan(plan_days_of(sc)),
                         "strength": cat in eligible, "last_quarter_score": round(prev[cat], 1), "same_quarter_last_year_score": round(year[cat], 1),
                         "qoq_trend": trend_label(sc - prev[cat]), "yoy_trend": trend_label(sc - year[cat]), "metrics": metrics}
        over = rows[["over_delivery_pct"]]["over_delivery_pct"]
        my_ini = ini[ini.supplier_id == sid]
        pipeline = {}
        for h in HORIZONS:
            part = my_ini[my_ini.horizon == h]
            funded = part[part.committed_to_date_usd > 0]
            pipeline[h] = {"initiatives": len(part), "annual_savings_target_usd": int(part.annual_savings_target_usd.sum()),
                           "committed_to_date_usd": int(funded.committed_to_date_usd.sum()), "realized_to_date_usd": int(funded.realized_to_date_usd.sum()),
                           "realized_pct_of_committed": round(100 * funded.realized_to_date_usd.sum() / funded.committed_to_date_usd.sum(), 1) if len(funded) else None}
        cards[sid] = {
            "supplier_id": sid, "name": s["name"], "country": s.country, "commodity": s.commodity, "quality_class": qc, "quarter": cur_q,
            "compared_with": {"last_quarter": qoq_q, "same_quarter_last_year": yoy_q},
            "overall_score": overall, "overall_flag": flag_of(overall), "overall_plan": make_plan(plan_days_of(overall)),
            "categories": cats,
            "major_issues": [c for c in cats if cats[c]["flag"] == "MAJOR_ISSUE"],
            "watch_categories": [c for c in cats if cats[c]["flag"] in ("WARNING", "CAUTION")],
            "strengths": eligible,
            "over_delivery": {"pct_this_quarter": float(over.loc[cur_q]), "limit_pct": OVER_DELIVERY_LIMIT,
                              "planning_review": bool(over.loc[cur_q] > OVER_DELIVERY_LIMIT),
                              "history": {q: float(over.loc[q]) for q in quarters}},
            "savings_pipeline": pipeline,
            "initiatives": [{"initiative_id": r.initiative_id, "type": r.type, "horizon": r.horizon, "description": r.description,
                             "annual_savings_target_usd": int(r.annual_savings_target_usd), "committed_to_date_usd": int(r.committed_to_date_usd),
                             "realized_to_date_usd": int(r.realized_to_date_usd),
                             "realized_pct_of_committed": round(100 * r.realized_to_date_usd / r.committed_to_date_usd, 1) if r.committed_to_date_usd else None,
                             "status": r.status, "target_completion_date": r.target_completion_date,
                             "follow_up": INITIATIVE_FOLLOW_UP[r.status][0] if r.status in INITIATIVE_FOLLOW_UP else None,
                             "follow_up_due": (AS_OF + dt.timedelta(days=INITIATIVE_FOLLOW_UP[r.status][1])).isoformat() if r.status in INITIATIVE_FOLLOW_UP else None}
                            for r in my_ini.itertuples()],
        }
    return cards


def results_table(cards):
    """One row per supplier and category, plus an OVERALL row, in the same shape as answer_key.csv."""
    rows = []
    for sid, c in cards.items():
        for cat, v in c["categories"].items():
            rows.append({"supplier_id": sid, "category": cat, "expected_score": v["score"], "flag": v["flag"],
                         "plan_days": v["plan"]["days"] if v["plan"] else None, "strength": v["strength"],
                         "qoq_trend": v["qoq_trend"], "yoy_trend": v["yoy_trend"], "overall_score": c["overall_score"]})
        rows.append({"supplier_id": sid, "category": "OVERALL", "expected_score": c["overall_score"], "flag": c["overall_flag"],
                     "plan_days": c["overall_plan"]["days"] if c["overall_plan"] else None, "strength": False,
                     "qoq_trend": "n/a", "yoy_trend": "n/a", "overall_score": c["overall_score"]})
    return pd.DataFrame(rows)


def main():
    data = read_data(".")
    cards = build_scorecards(data)
    table = results_table(cards)
    table.to_csv("scorecard_results.csv", index=False)
    ini_rows = [{"supplier_id": sid, **i} for sid, c in cards.items() for i in c["initiatives"]]
    pd.DataFrame(ini_rows).to_csv("initiative_status.csv", index=False)
    print(f"Scored {len(cards)} suppliers for {next(iter(cards.values()))['quarter']} (QBR date {AS_OF.isoformat()})\n")
    for sid, c in cards.items():
        parts = [f"{k[:4]} {v['score']}" for k, v in c["categories"].items()]
        print(f"{sid} {c['name']:<26} overall {c['overall_score']:.2f} {c['overall_flag']:<11} | " + "  ".join(parts))
        if c["major_issues"]:
            print(f"    MAJOR ISSUES: {', '.join(c['major_issues'])}")
        if c["watch_categories"]:
            print(f"    caution/warning: {', '.join(c['watch_categories'])}")
        if c["strengths"]:
            print(f"    strengths: {', '.join(c['strengths'])}")
        if c["over_delivery"]["planning_review"]:
            print(f"    OVER-DELIVERY {c['over_delivery']['pct_this_quarter']}% -> planning review")
    print("\nSaved scorecard_results.csv and initiative_status.csv")


if __name__ == "__main__":
    main()
