"""
Offline test: runs the whole agent loop with a STAND-IN for Claude (no API key, no cost).

The stand-in reads the tool results the real model would see and writes a QBR from them. It lets us
check that the tools, the checks, the retry and the file output work before spending any money.

  mode "good"    writes a correct QBR first time
  mode "sloppy"  first attempt contains deliberate mistakes (invented number, wrong category, bad
                 incident ID, wrong initiative status, a banned word); the second attempt is correct
  mode "stubborn" repeats the mistakes after the retry, so the QBR must be flagged for review

Run:  python test_offline.py
"""
import json
import os
import tempfile
from types import SimpleNamespace as NS

import agent
import qbr_checks as qc


def block_tool(i, name, **inp):
    return NS(type="tool_use", id=f"t{i}", name=name, input=inp)


class FakeClient:
    def __init__(self, mode):
        self.mode = mode
        self.messages = self
        self.sub_count = {}

    def create(self, model, max_tokens, system, tools, messages):
        sid = messages[0]["content"].split()[-1].rstrip(".")
        turns = sum(1 for m in messages if m["role"] == "assistant")
        usage = NS(input_tokens=1000, output_tokens=500)
        if turns == 0:
            blocks = [block_tool(i, n, supplier_id=sid) for i, n in enumerate(["get_scorecard", "get_incidents", "get_initiatives", "get_risk_outlook"])]
            return NS(content=blocks, stop_reason="tool_use", usage=usage)
        seen = {}
        for m in messages:
            if m["role"] == "user" and isinstance(m["content"], list):
                for r in m["content"]:
                    seen[r["tool_use_id"]] = json.loads(r["content"])
        card = next(v for v in seen.values() if isinstance(v, dict) and "must_mention" in v)
        incidents = next(v for v in seen.values() if isinstance(v, list))
        n = self.sub_count.get(sid, 0)
        self.sub_count[sid] = n + 1
        broken = self.mode == "stubborn" or (self.mode == "sloppy" and n == 0)
        return NS(content=[block_tool(10 + n, "submit_qbr", **compose(card, incidents, seen, broken))], stop_reason="tool_use", usage=usage)


def compose(card, incidents, seen, broken):
    cats = card["categories"]
    init = next(v for v in seen.values() if isinstance(v, dict) and "initiatives" in v)["initiatives"]
    risk = next(v for v in seen.values() if isinstance(v, dict) and "available" in v)
    issues = []
    for c in card["major_issues"]:
        v = cats[c]
        ev = [i["incident_id"] for i in incidents if i["category"].upper() == c.upper() and i["type"] == "INCIDENT"]
        m = ", ".join(f"{x['metric']} {x['value']:g}" for x in v["metrics"])
        trend = ("declining" if "DECLINING" in (v["qoq_trend"], v["yoy_trend"]) else "improving" if "IMPROVING" in (v["qoq_trend"], v["yoy_trend"]) else "stable")
        issues.append({"category": c, "what_happened": f"{c} scored {v['score']:.1f} ({m}); the score is {trend}.",
                       "likely_cause": (next((i["description"] for i in incidents if i["incident_id"] in ev), "")) or "cause not confirmed",
                       "evidence_incident_ids": ev if not (broken and ev) else ["INC-999"],
                       "corrective_actions": [f"Submit a recovery plan for {c} by {v['plan']['checkpoint_dates'][0]}.",
                                              f"Bring {c} back to a score of 3.0 or higher by {v['plan']['due_date']}."],
                       "supplier_commitment_needed": f"Written commitment by {v['plan']['checkpoint_dates'][0]}."})
    watch = [{"category": c, "note": f"{cats[c]['flag'].title()}: score {cats[c]['score']:.1f}; {cats[c]['plan']['days']}-day monitoring plan due {cats[c]['plan']['due_date']}."} for c in card["watch_categories"]]
    st = [{"category": c, "note": f"Score {cats[c]['score']:.1f}."} for c in card["strengths"]]
    flagged = [i for i in init if i["status"] in ("AT_RISK", "DELAYED", "WATCH")]
    unfunded = [i for i in init if i["status"] in ("NOT_STARTED", "IN_DESIGN")][:1]      # also mention a not-yet-funded item
    sav = "Savings are being realized across the short and medium horizons."
    sav += "".join(f" {i['initiative_id']} is {i['status'].replace('_', ' ').lower()} at {i['realized_pct_of_committed']}% of committed." for i in flagged[:1])
    sav += "".join(f" {i['initiative_id']} is {i['status'].replace('_', ' ').lower()} with nothing committed yet." for i in unfunded)
    od = card["over_delivery"]
    note = f"Over-delivery of {od['pct_this_quarter']}% is above the {od['limit_pct']}% limit; planning should decide whether to accept the extra material." if od["planning_review"] else ""
    risk_text = f"Supplier risk tier {risk['supplier_risk_tier']} (risk results as of {risk['risk_results_as_of']}): {risk['tier_reasons']}." if risk.get("available") else "Risk Detection Agent results were not loaded."
    sub = {"executive_summary": f"{card['name']} has an overall score of {card['overall_score']:.2f} ({card['overall_flag'].replace('_', ' ').lower()}).",
           "major_issues": issues, "watch_items": watch, "strengths": st, "savings_summary": sav, "planning_flag_note": note,
           "risk_outlook": risk_text, "asks_of_supplier": ["Confirm the corrective plan dates in writing.", "Report progress at each checkpoint."]}
    if broken:
        sub["asks_of_supplier"] = [{"ask": x} for x in sub["asks_of_supplier"]]      # objects instead of sentences
        sub["executive_summary"] += " This is a critical situation and scores fell by 17 points."
        if issues:
            issues[0]["category"] = "Quality" if issues[0]["category"] != "Quality" else "Delivery"
        if flagged:
            sub["savings_summary"] = sub["savings_summary"].replace("watch", "on track").replace("at risk", "on track")
    if broken:
        del sub["savings_summary"]                                                  # a required section left out
    return sub


def run(mode, ids):
    print(f"\n=== mode: {mode} ===")
    client, usage, summary = FakeClient(mode), {"in": 0, "out": 0}, {"pass": 0, "revised": 0, "flagged": 0}
    for sid in ids:
        r = agent.review_supplier(client, sid, usage)
        failed = [k for k in qc.CHECK_KEYS if not r["checks"][k]]
        summary["pass"] += not failed
        summary["revised"] += r["revised"]
        summary["flagged"] += bool(failed)
        agent.write_qbr(r)            # writes into a temporary folder, not your project folder
        if failed:
            print(f"  {sid} flagged: {failed}")
    print(f"  {len(ids)} suppliers: {summary['pass']} pass, {summary['revised']} revised after a failed check, {summary['flagged']} flagged for human review")
    return summary


if __name__ == "__main__":
    os.chdir(tempfile.mkdtemp())      # data was already loaded; outputs of this test go to a throwaway folder
    ids = list(agent.cards)
    s = run("good", ids)
    assert s["pass"] == 12 and s["revised"] == 0, s
    s = run("sloppy", ids)
    assert s["revised"] > 0 and s["flagged"] == 0, s
    s = run("stubborn", ids)
    assert s["flagged"] > 0, s
    print("\nAll offline tests behaved as expected.")
