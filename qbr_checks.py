"""
Checks on the QBR wording (no AI in this file).

The scorecard engine (scorecard.py) decides every number. This file builds
  - the "must mention" list the agent is given, and
  - the checks that confirm the agent's writing matches the data:
      * the right major issues, cautions and strengths are covered (no more, no fewer)
      * every number in the narrative appears in the data the agent was shown
      * causes are backed by real incident IDs for that supplier and category
      * initiative IDs are described with the status the rules assigned
      * the over-delivery flag is raised only when the rules raised it
"""
import os
import re

import pandas as pd

import scorecard as sc

ID_RE = re.compile(r"\b(?:SUP|INC|INI|PO|ITM|ALT)-\d+\b")
NUM_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
ALWAYS_OK_NUMBERS = {1, 2, 3, 4, 5, 100}          # the 1-to-5 scale and percentages
BANNED_WORDS = ["critical", "critically", "catastrophic", "disastrous", "unacceptable", "unauthorized", "illegal", "fraudulent", "negligent"]
# maximum words per field, so every section can sit on a slide
LIMITS = {"executive_summary": 45, "what_happened": 45, "likely_cause": 35, "corrective_action": 22, "supplier_commitment_needed": 25,
          "note": 22, "savings_summary": 50, "planning_flag_note": 35, "risk_outlook": 35, "ask": 22}
MAX_ACTIONS, MAX_ASKS = 3, 3
CHECK_KEYS = ["fields_ok", "length_ok", "issues_ok", "detail_ok", "causes_ok", "watch_ok", "strengths_ok", "savings_ok",
              "delivery_flag_ok", "summary_ok", "numbers_ok", "ids_ok", "tone_ok", "risk_ok"]
CHECK_LABELS = {"fields_ok": "Complete and well-formed", "length_ok": "Concise (slide-ready)", "issues_ok": "Major issues covered", "detail_ok": "Issue detail (score, due date, trend, actions)",
                "causes_ok": "Causes backed by incidents", "watch_ok": "Caution items covered", "strengths_ok": "Strengths",
                "savings_ok": "Savings initiative statuses", "delivery_flag_ok": "Over-delivery flag", "summary_ok": "Executive summary",
                "numbers_ok": "Numbers grounded in data", "ids_ok": "IDs valid", "tone_ok": "Tone", "risk_ok": "Risk outlook"}
STATUS_WORDS = {"AT_RISK": ["at risk", "at-risk", "at_risk"], "WATCH": ["watch"], "DELAYED": ["delayed", "past its target", "past its date"],
                "ON_TRACK": ["on track", "on-track", "on_track"], "AHEAD_OF_PLAN": ["ahead"],
                "NOT_STARTED": ["not started", "not yet started", "not_started", "no work", "yet to start", "nothing committed"],
                "IN_DESIGN": ["in design", "in_design", "design phase", "being designed", "scoping", "nothing committed"]}
DOWN_WORDS = ["declin", "worsen", "fell", "fall", "drop", "deteriorat", "slip", "lower", "decreas", "down"]
UP_WORDS = ["improv", "rose", "rise", "better", "increas", "gain", "up from"]


STATUS_KEY = ("AHEAD_OF_PLAN 100%+ of committed | ON_TRACK 75% to under 100% | WATCH 70% to under 75% | "
              "AT_RISK under 70% | DELAYED target date passed and below committed | IN_DESIGN / NOT_STARTED nothing committed")


def numbers_in(text):
    return {float(m.replace(",", "")) for m in NUM_RE.findall(ID_RE.sub(" ", str(text)))}


def ids_in(text):
    return set(ID_RE.findall(str(text)))


# ------------------------------------------------------------------
# Optional link to the Risk Detection Agent's results
# ------------------------------------------------------------------
RISK_AS_OF = "2026-10-02"        # the date the Risk Detection Agent results were produced


def load_risk(folder="."):
    """If supplier_tiers.csv and risk_assessment.csv (from the risk agent) are in the folder, link them in."""
    t, a = f"{folder}/supplier_tiers.csv", f"{folder}/risk_assessment.csv"
    if not (os.path.exists(t) and os.path.exists(a)):
        return None
    tiers = pd.read_csv(t, dtype=str, keep_default_na=False).set_index("supplier_id")
    assess = pd.read_csv(a, dtype=str, keep_default_na=False)
    out = {}
    for sid in tiers.index:
        mine = assess[assess.supplier_id == sid]
        out[sid] = {"risk_results_as_of": RISK_AS_OF, "supplier_risk_tier": tiers.loc[sid, "tier"], "tier_reasons": tiers.loc[sid, "reasons"],
                    "items_at_high_risk": list(mine[mine.risk_level == "HIGH"].item_id),
                    "items_at_medium_risk": list(mine[mine.risk_level == "MEDIUM"].item_id)}
    return out


# ------------------------------------------------------------------
# What the agent must cover (decided by code)
# ------------------------------------------------------------------
def flagged_initiatives(card):
    return [i for i in card["initiatives"] if i["status"] in ("AT_RISK", "DELAYED", "WATCH")]


def required_facts(card):
    f = [f"Overall score {card['overall_score']:.2f} ({card['overall_flag']})."]
    if card["overall_plan"]:
        f.append(f"The overall score is below 3.0, so an overall corrective plan of {card['overall_plan']['days']} days is due {card['overall_plan']['due_date']}.")
    if not card["major_issues"]:
        f.append("There are no major issues this quarter.")
    for c in card["major_issues"]:
        v = card["categories"][c]
        f.append(f"MAJOR ISSUE {c}: score {v['score']:.1f}; {v['plan']['days']}-day corrective plan due {v['plan']['due_date']} "
                 f"(checkpoints {', '.join(v['plan']['checkpoint_dates'])}); trend vs last quarter {v['qoq_trend']}, vs last year {v['yoy_trend']}.")
    for c in card["watch_categories"]:
        v = card["categories"][c]
        f.append(f"{v['flag']} {c}: score {v['score']:.1f}; {v['plan']['days']}-day monitoring plan due {v['plan']['due_date']}.")
    for c in card["strengths"]:
        f.append(f"STRENGTH {c}: score {card['categories'][c]['score']:.1f}.")
    if not card["strengths"]:
        f.append("There are no strengths to report this quarter (no category scored 4.0 or higher).")
    od = card["over_delivery"]
    if od["planning_review"]:
        f.append(f"OVER-DELIVERY {od['pct_this_quarter']}% is above the {od['limit_pct']}% limit: planning should decide whether to accept the extra material to protect planned inventory levels.")
    if flagged_initiatives(card):
        f.append("Initiatives that are AT_RISK, DELAYED or WATCH are listed with their status, follow-up and due date in a table the system builds. "
                 "Do not list them one by one. If you mention an initiative by ID, use the status the rules gave it.")
    return f


def tidy(x):
    """Show whole numbers without a trailing .0 (1400.0 -> 1400, 96.0 -> 96)."""
    if isinstance(x, float) and x == int(x):
        return int(x)
    if isinstance(x, dict):
        return {k: tidy(v) for k, v in x.items()}
    if isinstance(x, list):
        return [tidy(v) for v in x]
    return x


def tool_view(card, risk=None):
    """What get_scorecard hands to the model."""
    view = {k: v for k, v in card.items() if k not in ("initiatives",)}
    view["rules"] = {"scale": "1 to 5 (5 exceeds, 3 meets, 2 below expectations, 1 poor)", "major_issue_at_or_below": sc.MAJOR_MAX,
                     "trend_threshold": sc.TREND_THRESHOLD, "strength_at_or_above": sc.STRENGTH_MIN,
                     "plan_lengths_days": {"score_2.0_or_below": 30, "score_2.1_to_below_2.5": 60, "score_2.5_to_below_3.0": 90}}
    view["must_mention"] = required_facts(card)
    return tidy(view)


# ------------------------------------------------------------------
# The checks
# ------------------------------------------------------------------
STR_FIELDS = ["executive_summary", "savings_summary", "planning_flag_note", "risk_outlook"]
ISSUE_STR = ["category", "what_happened", "likely_cause", "supplier_commitment_needed"]


def _as_text(x):
    """A model sometimes sends {'ask': '...'} instead of '...'. Return plain text."""
    if isinstance(x, dict):
        return " ".join(str(v) for v in x.values())
    return str(x)


def normalize(sub):
    """Make a model's submission safe to use. Returns (clean_submission, problems to send back to the model)."""
    prob, out = [], {}
    sub = sub if isinstance(sub, dict) else {}
    for k in STR_FIELDS:
        if k not in sub or sub[k] is None:
            if k != "planning_flag_note":
                prob.append(f"{k} is missing: include it")
            out[k] = ""
        else:
            out[k] = _as_text(sub[k])
    for k in ("watch_items", "strengths"):
        items = sub.get(k)
        if not isinstance(items, list):
            prob.append(f"{k} must be a list (use an empty list if there are none)")
            items = []
        out[k] = [{"category": _as_text(w.get("category", "")), "note": _as_text(w.get("note", ""))} if isinstance(w, dict)
                  else {"category": "", "note": _as_text(w)} for w in items]
    asks = sub.get("asks_of_supplier")
    if not isinstance(asks, list):
        prob.append("asks_of_supplier must be a list of plain sentences")
        asks = []
    if any(not isinstance(a, str) for a in asks):
        prob.append("each item in asks_of_supplier must be a plain sentence, not an object")
    out["asks_of_supplier"] = [_as_text(a) for a in asks]
    issues = sub.get("major_issues")
    if not isinstance(issues, list):
        prob.append("major_issues must be a list (use an empty list if there are none)")
        issues = []
    out["major_issues"] = []
    for i in issues:
        i = i if isinstance(i, dict) else {}
        c = {k: _as_text(i.get(k, "")) for k in ISSUE_STR}
        miss = [k for k in ISSUE_STR + ["corrective_actions", "evidence_incident_ids"] if k not in i]
        if miss:
            prob.append(f"{c['category'] or 'a major issue'}: missing {', '.join(miss)}")
        for k in ("corrective_actions", "evidence_incident_ids"):
            v = i.get(k, [])
            c[k] = [_as_text(x) for x in v] if isinstance(v, list) else [_as_text(v)]
        out["major_issues"].append(c)
    return out, prob


def _issue_text(i):
    return " ".join([str(i.get("what_happened", "")), str(i.get("likely_cause", "")), str(i.get("supplier_commitment_needed", "")),
                     " ".join(map(str, i.get("corrective_actions", []) or []))])


def all_text(sub):
    parts = [sub.get("executive_summary", ""), sub.get("savings_summary", ""), sub.get("risk_outlook", ""), sub.get("planning_flag_note", "")]
    parts += [_issue_text(i) for i in sub.get("major_issues", []) or []]
    parts += [str(w.get("note", "")) for w in sub.get("watch_items", []) or []]
    parts += [str(w.get("note", "")) for w in sub.get("strengths", []) or []]
    parts += [str(a) for a in sub.get("asks_of_supplier", []) or []]
    return " ".join(map(str, parts))


def allowed_from(seen_text):
    nums = numbers_in(seen_text)
    return nums | {round(n) for n in nums} | ALWAYS_OK_NUMBERS


def check_qbr(card, sub, seen_text, incidents, risk=None):
    """Returns ({check: bool}, {check: [problems]}). `seen_text` is everything the model was shown."""
    prob = {k: [] for k in CHECK_KEYS}
    sub, prob["fields_ok"] = normalize(sub)
    cats = card["categories"]
    issues = {i.get("category"): i for i in sub.get("major_issues", []) or []}
    given = [i.get("category") for i in sub.get("major_issues", []) or []]

    # 0. slide-ready length
    def too_long(label, text, key):
        n = len(str(text).split())
        if n > LIMITS[key]:
            prob["length_ok"].append(f"{label} is {n} words; shorten it to {LIMITS[key]} words or fewer")
    too_long("executive_summary", sub.get("executive_summary", ""), "executive_summary")
    too_long("savings_summary", sub.get("savings_summary", ""), "savings_summary")
    too_long("planning_flag_note", sub.get("planning_flag_note", ""), "planning_flag_note")
    too_long("risk_outlook", sub.get("risk_outlook", ""), "risk_outlook")
    for i in sub.get("major_issues", []) or []:
        c = i.get("category")
        for f in ("what_happened", "likely_cause", "supplier_commitment_needed"):
            too_long(f"{c} {f}", i.get(f, ""), f)
        acts = i.get("corrective_actions", []) or []
        if len(acts) > MAX_ACTIONS:
            prob["length_ok"].append(f"{c}: give at most {MAX_ACTIONS} corrective actions")
        for a in acts:
            too_long(f"{c} corrective action", a, "corrective_action")
    for w in (sub.get("watch_items", []) or []) + (sub.get("strengths", []) or []):
        too_long(f"{w.get('category')} note", w.get("note", ""), "note")
    asks = sub.get("asks_of_supplier", []) or []
    if len(asks) > MAX_ASKS:
        prob["length_ok"].append(f"give at most {MAX_ASKS} asks_of_supplier")
    for a in asks:
        too_long("an ask", a, "ask")

    # 1. exactly the major issues the rules found
    if sorted(given) != sorted(card["major_issues"]):
        prob["issues_ok"].append(f"major_issues must cover exactly {card['major_issues'] or 'none'}; you listed {given or 'none'}")

    # 2/3. detail and causes for each major issue
    inc = incidents[incidents.supplier_id == card["supplier_id"]]
    for c in card["major_issues"]:
        i = issues.get(c)
        if not i:
            continue
        v, text = cats[c], _issue_text(i)
        nums = numbers_in(text)
        if v["plan"]["due_date"] not in text:
            prob["detail_ok"].append(f"{c}: include the corrective plan due date {v['plan']['due_date']} exactly as written")
        low = text.lower()
        trends = {v["qoq_trend"], v["yoy_trend"]}
        if "DECLINING" in trends and not any(w in low for w in DOWN_WORDS):
            prob["detail_ok"].append(f"{c}: say that the score is declining (QoQ {v['qoq_trend']}, YoY {v['yoy_trend']})")
        if "IMPROVING" in trends and not any(w in low for w in UP_WORDS):
            prob["detail_ok"].append(f"{c}: say that the score is improving (QoQ {v['qoq_trend']}, YoY {v['yoy_trend']})")
        if len(i.get("corrective_actions", []) or []) < 2:
            prob["detail_ok"].append(f"{c}: give at least 2 corrective actions")
        cited = list(i.get("evidence_incident_ids", []) or [])
        valid = set(inc[(inc.category.str.upper() == c.upper()) & (inc.type == "INCIDENT")].incident_id)
        bad = [x for x in cited if x not in valid]
        if bad:
            prob["causes_ok"].append(f"{c}: {', '.join(bad)} is not an INCIDENT for this supplier in the {c} category")
        if valid and not [x for x in cited if x in valid]:
            prob["causes_ok"].append(f"{c}: cite at least one of these incidents as evidence: {', '.join(sorted(valid))}")
        if not valid and not any(p in str(i.get("likely_cause", "")).lower() for p in ["no incident", "not confirmed", "no evidence"]):
            prob["causes_ok"].append(f"{c}: there is no incident on file, so say the cause is not confirmed instead of guessing")

    # 4. caution items
    watch = {w.get("category"): w for w in sub.get("watch_items", []) or []}
    if sorted(watch) != sorted(card["watch_categories"]):
        prob["watch_ok"].append(f"watch_items must cover exactly {card['watch_categories'] or 'none'}; you listed {list(watch) or 'none'}")

    # 5. strengths
    st = {w.get("category"): w for w in sub.get("strengths", []) or []}
    if sorted(st) != sorted(card["strengths"]):
        prob["strengths_ok"].append(f"strengths must be exactly {card['strengths'] or 'none (leave the list empty)'}; you listed {list(st) or 'none'}")

    # 6. savings initiative statuses
    sav = str(sub.get("savings_summary", ""))
    by_id = {i["initiative_id"]: i for i in card["initiatives"]}
    for m in re.finditer(r"INI-\d+", sav):
        i = by_id.get(m.group())
        if not i:
            continue
        window = sav[max(0, m.start() - 90): m.end() + 130].lower()
        if not any(w in window for w in STATUS_WORDS.get(i["status"], [i["status"].lower()])):
            prob["savings_ok"].append(f"{i['initiative_id']} is {i['status']} per the rules; describe it with that status")

    # 7. over-delivery flag
    od, note = card["over_delivery"], str(sub.get("planning_flag_note", "")).strip()
    if od["planning_review"]:
        if not any(abs(n - od["pct_this_quarter"]) < 1e-9 for n in numbers_in(note)) or "planning" not in note.lower():
            prob["delivery_flag_ok"].append(f"planning_flag_note must state the {od['pct_this_quarter']}% over-delivery and that planning should decide whether to accept the extra material")
    elif note or "planning review" in all_text(sub).lower():
        prob["delivery_flag_ok"].append(f"over-delivery is {od['pct_this_quarter']}%, not above the {od['limit_pct']}% limit: leave planning_flag_note empty and do not raise a planning review")

    # 8. executive summary
    es = str(sub.get("executive_summary", ""))
    if card["name"].lower() not in es.lower():
        prob["summary_ok"].append(f"executive_summary must name the supplier ({card['name']})")
    if not any(abs(n - card["overall_score"]) < 0.005 for n in numbers_in(es)):
        prob["summary_ok"].append(f"executive_summary must state the overall score {card['overall_score']:.2f}")

    text = all_text(sub)
    # 9. numbers must come from the data
    ok_nums = allowed_from(seen_text)
    odd = sorted(n for n in numbers_in(text) if n not in ok_nums)
    if odd:
        prob["numbers_ok"].append("these numbers do not appear in the data: " + ", ".join(f"{n:g}" for n in odd) + ". Quote numbers exactly as given; do not calculate new ones")
    # 10. IDs must come from the data
    seen_ids = ids_in(seen_text)
    odd_ids = sorted(ids_in(text) - seen_ids)
    if odd_ids:
        prob["ids_ok"].append("IDs not in the data: " + ", ".join(odd_ids))
    # 11. tone
    hit = [w for w in BANNED_WORDS if re.search(rf"\b{w}\b", text.lower())]
    if hit:
        prob["tone_ok"].append("remove these words and show urgency with dates and numbers instead: " + ", ".join(hit))
    # 12. risk outlook
    if risk and card["supplier_id"] in risk:
        r = risk[card["supplier_id"]]
        if r["supplier_risk_tier"].lower() not in str(sub.get("risk_outlook", "")).lower():
            prob["risk_ok"].append(f"risk_outlook must state the supplier's risk tier ({r['supplier_risk_tier']})")
        if RISK_AS_OF not in str(sub.get("risk_outlook", "")):
            prob["risk_ok"].append(f"risk_outlook must say the risk results are as of {RISK_AS_OF}, because the QBR is dated later")
    checks = {k: not prob[k] for k in CHECK_KEYS}
    return checks, prob


def fix_instructions(prob):
    lines = []
    for k in CHECK_KEYS:
        for p in prob[k]:
            lines.append(f"[{CHECK_LABELS[k]}] {p}")
    return lines
