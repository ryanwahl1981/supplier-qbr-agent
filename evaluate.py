"""
Evaluation: how well did the rules engine and the agent do compared with the hand-written answer key?

Part A (the rules engine, no AI):
  1. Category scores, flags, plan lengths, strengths and trends match answer_key.csv
  2. Initiative statuses recomputed from the savings numbers match initiatives.csv
  3. Over-delivery planning flags match answer_key_overdelivery.csv

Part B (the agent's QBRs, from qbr_results.json), graded against the ANSWER KEY, not against the engine:
  4. Coverage          - how many suppliers got a QBR?
  5. Major issues      - exactly the key's major-issue categories, each with its due date
  6. Cautions          - exactly the key's caution categories
  7. Strengths         - exactly the key's strengths (1 or 2, or none)
  8. Causes            - every cited incident ID is a real INCIDENT for that supplier and category;
                         "cause not confirmed" where no incident exists
  9. Savings           - flagged initiatives (AT_RISK, DELAYED, WATCH) are described with the right status
 10. Over-delivery     - flagged only for the supplier(s) the key says
 11. Grounding         - every number and ID in the narrative appears in the data the agent was shown
 12. Tone, length (slide-ready), summary, risk outlook, issue detail
"""
import datetime as dt
import json
import os

import pandas as pd

import qbr_checks as qc
import scorecard as sc

key = pd.read_csv("answer_key.csv", keep_default_na=False, na_values=[""])
okey = pd.read_csv("answer_key_overdelivery.csv")
data = sc.read_data(".")
cards = sc.build_scorecards(data)
risk = qc.load_risk(".")
incidents = data["incidents"]

# ---------------- Part A ----------------
res = sc.results_table(cards)
m = key.merge(res, on=["supplier_id", "category"], suffixes=("_k", "_r"))
cols = ["expected_score", "flag", "plan_days", "strength", "qoq_trend", "yoy_trend", "overall_score"]
bad = [(r.supplier_id, r.category, c) for r in m.itertuples() for c in cols
       if not (getattr(r, c + "_k") == getattr(r, c + "_r") or (pd.isna(getattr(r, c + "_k")) and pd.isna(getattr(r, c + "_r"))))]
print("PART A: rules engine vs answer key")
print(f"1. Scorecard:     {len(m) * len(cols) - len(bad)}/{len(m) * len(cols)} values match ({len(m)} supplier/category rows)")
for b in bad:
    print("   mismatch:", b)
file_status = data["initiatives"].set_index("initiative_id").status
eng_status = {i["initiative_id"]: i["status"] for c in cards.values() for i in c["initiatives"]}
wrong = [i for i in file_status.index if eng_status[i] != file_status[i]]
print(f"2. Initiatives:   {len(file_status) - len(wrong)}/{len(file_status)} statuses match the rules")
od_bad = [r.supplier_id for r in okey.itertuples() if cards[r.supplier_id]["over_delivery"]["planning_review"] != bool(r.planning_review_flag)]
print(f"3. Over-delivery: {len(okey) - len(od_bad)}/{len(okey)} planning flags match the key")

# ---------------- Part B ----------------
if not os.path.exists("qbr_results.json"):
    print("\nPART B: no qbr_results.json yet. Run agent.py first.")
    raise SystemExit
results = {r["supplier_id"]: r for r in json.load(open("qbr_results.json", encoding="utf-8"))}
print(f"\nPART B: agent QBRs ({len(results)} written)")
print(f"4. Coverage:      {len(results)}/{len(cards)} suppliers have a QBR" + ("" if len(results) == len(cards) else "  (MAX_SUPPLIERS in agent.py may have limited the run)"))

fails = {n: [] for n in range(5, 13)}
by_check = {k: 0 for k in qc.CHECK_KEYS}
due = lambda days: (sc.AS_OF + dt.timedelta(days=int(days))).isoformat()
for sid, r in results.items():
    sub, k = r["submission"], key[key.supplier_id == sid].set_index("category")
    cat_rows = k.drop("OVERALL")
    text_of = lambda i: qc._issue_text(i)
    # 5 major issues
    want = sorted(cat_rows[cat_rows.flag == "MAJOR_ISSUE"].index)
    got = sorted(i["category"] for i in sub["major_issues"])
    if want != got:
        fails[5].append(f"{sid}: key {want}, QBR {got}")
    for i in sub["major_issues"]:
        if i["category"] in cat_rows.index and cat_rows.loc[i["category"]].flag == "MAJOR_ISSUE":
            row = cat_rows.loc[i["category"]]
            t = text_of(i)
            if due(row.plan_days) not in t:
                fails[5].append(f"{sid} {i['category']}: due date {due(row.plan_days)} missing from the actions")
    # 6 cautions
    want = sorted(cat_rows[cat_rows.flag.isin(["CAUTION", "WARNING"])].index)
    got = sorted(w["category"] for w in sub["watch_items"])
    if want != got:
        fails[6].append(f"{sid}: key {want}, QBR {got}")
    # 7 strengths
    want = sorted(cat_rows[cat_rows.strength == True].index)
    got = sorted(w["category"] for w in sub["strengths"])
    if want != got:
        fails[7].append(f"{sid}: key {want}, QBR {got}")
    # re-run the code checks on the final saved text, using everything the agent could have been shown
    c = cards[sid]
    seen = json.dumps([qc.tool_view(c, risk), c["initiatives"], qc.STATUS_KEY, incidents[incidents.supplier_id == sid].to_dict("records"),
                       risk.get(sid) if risk else None], default=str)
    checks, prob = qc.check_qbr(c, sub, seen, incidents, risk)
    for name in qc.CHECK_KEYS:
        by_check[name] += checks[name]
    if not checks["causes_ok"]:
        fails[8].append(f"{sid}: " + "; ".join(prob["causes_ok"]))
    if not checks["savings_ok"]:
        fails[9].append(f"{sid}: " + "; ".join(prob["savings_ok"]))
    said_flag = bool(str(sub.get("planning_flag_note", "")).strip())
    want_flag = bool(okey[okey.supplier_id == sid].planning_review_flag.iloc[0])
    if said_flag != want_flag or not checks["delivery_flag_ok"]:
        fails[10].append(f"{sid}: key says flag={want_flag}, QBR flag={said_flag}")
    if not (checks["numbers_ok"] and checks["ids_ok"]):
        fails[11].append(f"{sid}: " + "; ".join(prob["numbers_ok"] + prob["ids_ok"]))
    other = [x for name in ("tone_ok", "summary_ok", "risk_ok", "detail_ok", "length_ok") for x in prob[name]]
    if other:
        fails[12].append(f"{sid}: " + "; ".join(other))

n = len(results)
labels = {5: "Major issues", 6: "Cautions", 7: "Strengths", 8: "Causes", 9: "Savings", 10: "Over-delivery", 11: "Grounding", 12: "Tone/length/summary/detail"}
for num in range(5, 13):
    print(f"{num}. {labels[num] + ':':<26}{n - len({f.split(':')[0].split()[0] for f in fails[num]})}/{n} QBRs pass")
    for f in fails[num]:
        print("   ", f)
revised = sum(1 for r in results.values() if r["revised"])
print(f"\nInfo: {revised}/{n} QBRs needed one revision after failing a check (the scores above are the final results)")
