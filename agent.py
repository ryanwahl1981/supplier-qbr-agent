"""
Supplier Performance + Procurement QBR Agent

What it does:
  1. scorecard.py (code, no AI) scores every supplier: category scores, flags, corrective-plan
     lengths and due dates, strengths, quarter-over-quarter and year-over-year trends,
     savings initiative statuses and the over-delivery flag.
  2. For each supplier, Claude investigates using TOOLS:
       get_scorecard      the scorecard results, 8-quarter metric history and a must_mention list
       get_incidents      dated incidents and commendations (the ONLY evidence allowed for causes)
       get_initiatives    engineering and logistics savings initiatives by horizon
       get_risk_outlook   the supplier's tier and at-risk parts from the Risk Detection Agent (if present)
  3. Claude writes the QBR narrative (submit_qbr): executive summary, major issues with causes and
     corrective actions, caution items, strengths, savings, asks of the supplier, risk outlook.
  4. qbr_checks.py (code) checks the writing against the data. A failed QBR is sent back ONCE with
     exact fixes. If it still fails, it is saved and marked for human review.
  5. Output: QBR_<supplier>.md for each supplier, qbr_summary.md and qbr_results.json.

Important: the agent NEVER changes data or contacts a supplier. It only drafts. Scores, flags,
plan lengths, due dates and statuses are set by CODE, not by the model.

Run order:   python scorecard.py   (optional: see the scores)
             python agent.py       (writes the QBRs)
"""
import json
import os
import textwrap

import anthropic
import pandas as pd

import qbr_checks as qc
import scorecard as sc

# ------------------------------------------------------------------
# SETTINGS (edit these)
# ------------------------------------------------------------------
MODEL = "claude-haiku-4-5-20251001"   # smallest, cheapest Claude model
MAX_SUPPLIERS = 12                     # suppliers to review. Raise to 12 after a test run.
ONLY_SUPPLIERS = []                   # or pick yourself, e.g. ["SUP-004", "SUP-007"]
MAX_TURNS = 8                         # safety limit: max back-and-forth steps per supplier
PRICE_IN = 1.00                       # $ per million input tokens  (rough estimate, check current pricing)
PRICE_OUT = 5.00                      # $ per million output tokens (rough estimate, check current pricing)

SYSTEM_PROMPT = """You are a procurement analyst assistant drafting a Quarterly Business Review (QBR) for ONE supplier.
Do this:
1. Call get_scorecard, get_incidents, get_initiatives and get_risk_outlook for the supplier.
2. Call submit_qbr exactly once.

Rules:
- Use only facts from the tool results. Never invent causes, events, dates, people or numbers.
- Scores, flags, trends, plan lengths, due dates and initiative statuses are decided by the system. Quote them
  exactly as given. Never recalculate, round differently or change them.
- Quote every number exactly as it appears in the tool results (scores like 1.5, percentages, dollar amounts written
  in full such as $36,800, dates written as YYYY-MM-DD). Do NOT calculate new numbers (no differences, totals or averages).
- get_scorecard returns a must_mention list. Every fact in it must appear in your QBR, in your own words,
  with the same IDs, categories, scores and dates.
- major_issues: one entry for EVERY category flagged MAJOR_ISSUE and no others. For each give:
    what_happened: the metric values behind the low score and the trend (use qoq_trend and yoy_trend: say declining,
      improving or stable versus last quarter and versus last year).
    likely_cause: only from incidents in get_incidents. Cite their IDs in evidence_incident_ids (INCIDENT type, same
      category). If no incident explains it, write "cause not confirmed" and do not guess.
    corrective_actions: 2 or 3 concrete actions, each tied to the metric. Include the plan due date exactly as given
      and the target (the category score back to 3.0 or higher, using value_needed_for_a_3 for the metrics).
    supplier_commitment_needed: what the supplier must commit to by the first checkpoint date.
- watch_items: one short entry for every category flagged CAUTION or WARNING and no others. The system prints the score and the
  monitoring plan dates, so the note only says which metric is weak and what to watch (one sentence, no repeated score or date).
- strengths: one entry for each category in the strengths list and no others. If the list is empty, leave it empty.
  The system prints the score, so the note gives the supporting metric values in one sentence. Cite a COMMENDATION incident ID if one fits.
- savings_summary: 2 or 3 short sentences on how the savings pipeline is performing by horizon (SHORT, MEDIUM, LONG), using
  get_initiatives. Do NOT list the AT_RISK, DELAYED or WATCH initiatives one by one: the system adds a table of them with
  status, follow-up and due date. If you do mention an initiative by ID, use its status exactly (never call a WATCH
  initiative on track). Savings over 100% of committed are a positive (cost came in below plan).
- Do not invent any date or checkpoint: use only dates that appear in the tool results. Write statuses in plain words
  ("at risk", "on watch"), not AT_RISK.
- Keep every action and ask inside the category it addresses. Do not use metrics from another category (for example, do not
  ask an Engineering issue to fix corrective-action closure days, which is Quality).
- planning_flag_note: only if over_delivery.planning_review is true: state the over-delivery % and that planning should
  decide whether to accept the extra material to protect planned inventory levels. Otherwise leave it empty.
- Where lower is better (defects per million, closure days, response days, price variance), say "better than target" or "below
  the limit", never "above target". Where higher is better, say "above target".
- risk_outlook: say the risk results are "as of" the risk_results_as_of date (they are older than the QBR date, so do not
  present risk-agent figures such as days late as current). Then use get_risk_outlook (supplier risk tier, reasons, at-risk part IDs). If it is not available, say the
  Risk Detection Agent results were not loaded.
- Never describe anything as "critical", "catastrophic" or "unacceptable". Show urgency with dates and numbers.
- likely_cause must restate only what the incident descriptions say. Do not name a mechanism, department or reason that the
  record does not state (for example "review cycles", "capacity", "staffing") and do not build actions or commitments on
  such a guess. Aim each action at the problem the record shows (for example, answering design changes within the target
  days, or giving a tooling approval date). If the record does not explain the cause, say the root cause is to be confirmed
  and make "submit a verified root cause" one of the actions.
- Name metrics exactly as the tool results do and state targets in the metric's own terms (for example "design savings
  delivered at 70% of committed or higher", "design-change response of 7 days or fewer"). Do not invent steps such as
  "qualification" that the record does not mention.
- Describe supplier conduct neutrally, in the words of the incident record. Do not use "unauthorized", "illegal",
  "fraudulent" or "negligent". Say what the record says (for example, "outside the contract index clause").
- executive_summary: state the overall score and that it is below or above the 3.0 threshold (never "down from 3.0"),
  name the main issues, and name the strengths if there are any.
- Write each corrective action as one short instruction to the supplier: what we want them to do, the deliverable, and
  the date (for example, "Submit a verified root cause for the plating defect by 2026-10-28"). Keep it plain and brief.
- asks_of_supplier: if get_risk_outlook shows the supplier is high risk because of weak financial health, include one short
  ask for a financial recovery plan or a status update (for example, "Share a financial recovery plan by <checkpoint date>").
  Otherwise do not add a financial ask.
- Every corrective action must be a specific step the supplier takes, with a deliverable and a date. Do not write an action
  that only restates the goal (such as "target the score to 3.0 or higher") and do not use vague phrases such as
  "cost restructuring".
- asks_of_supplier: 2 or 3 specific, measurable asks that follow from the findings, each a plain sentence (not an object).
  Every deadline must be an exact date from the tool results (plan due dates, checkpoint dates, follow_up_due dates).
  Never write "within N days" for an ask.
- WRITE FOR A SLIDE. Be brief and plain. Hard limits in words: executive_summary 45 (2 sentences, name the supplier and the
  overall score); what_happened 45; likely_cause 35; each corrective action 22 (at most 3); supplier_commitment_needed 25;
  each watch or strength note 22; savings_summary 70; planning_flag_note 35; risk_outlook 35; each ask 22 (at most 3).
  Lead with the number, then the meaning. Do not list every quarter of history: give this quarter, last quarter or last
  year, and the target. Do not give ranges or combined percentages."""

# ------------------------------------------------------------------
# DATA
# ------------------------------------------------------------------
data = sc.read_data(".")
cards = sc.build_scorecards(data)
incidents = data["incidents"]
risk = qc.load_risk(".")


# ------------------------------------------------------------------
# TOOLS: ordinary Python functions that Claude is allowed to call
# ------------------------------------------------------------------
def get_scorecard(supplier_id):
    if supplier_id not in cards:
        return {"error": f"{supplier_id} not found"}
    return qc.tool_view(cards[supplier_id], risk)


def get_incidents(supplier_id):
    rows = incidents[incidents.supplier_id == supplier_id]
    return rows.to_dict("records") or "no incidents or commendations on file"


def get_initiatives(supplier_id):
    if supplier_id not in cards:
        return {"error": f"{supplier_id} not found"}
    c = cards[supplier_id]
    return {"savings_pipeline_by_horizon": qc.tidy(c["savings_pipeline"]), "initiatives": qc.tidy(c["initiatives"]),
            "status_key": qc.STATUS_KEY}


def get_risk_outlook(supplier_id):
    if risk is None or supplier_id not in risk:
        return {"available": False, "note": "Risk Detection Agent results (supplier_tiers.csv, risk_assessment.csv) were not loaded"}
    return {"available": True, **risk[supplier_id]}


def run_tool(name, args, supplier_id, state):
    if name == "get_scorecard":
        out = get_scorecard(args["supplier_id"])
    elif name == "get_incidents":
        out = get_incidents(args["supplier_id"])
    elif name == "get_initiatives":
        out = get_initiatives(args["supplier_id"])
    elif name == "get_risk_outlook":
        out = get_risk_outlook(args["supplier_id"])
    elif name == "submit_qbr":
        return submit(args, supplier_id, state)
    else:
        out = {"error": f"unknown tool {name}"}
    state["seen"] += json.dumps(out, default=str) + " "     # everything the model has been shown
    return out


def submit(args, supplier_id, state):
    card = cards[supplier_id]
    checks, problems = qc.check_qbr(card, args, state["seen"], incidents, risk)
    failed = [k for k in qc.CHECK_KEYS if not checks[k]]
    if failed and state["attempts"] == 0:
        # Validate-and-retry: send it back once with exact instructions on what to fix
        state["attempts"] = 1
        state["first_failed"] = failed
        return {"status": "REJECTED - not saved. Fix these problems and call submit_qbr again with the complete QBR.",
                "fix_these": qc.fix_instructions(problems)}
    state["result"] = {"supplier_id": supplier_id, "submission": qc.normalize(args)[0], "checks": checks,
                       "problems": {k: v for k, v in problems.items() if v}, "revised": state["attempts"] > 0,
                       "first_failed": state.get("first_failed", [])}
    return {"status": "QBR saved"}


def schema(field):
    return {"type": "object", "properties": {field: {"type": "string"}}, "required": [field]}


STR_LIST = {"type": "array", "items": {"type": "string"}}
TOOLS = [
    {"name": "get_scorecard", "input_schema": schema("supplier_id"),
     "description": "Scorecard results for the supplier: overall score, category scores, flags, corrective plans, strengths, trends, 8-quarter metric history, over-delivery, savings pipeline and the must_mention list."},
    {"name": "get_incidents", "input_schema": schema("supplier_id"),
     "description": "Dated incidents and commendations for the supplier. The only evidence allowed for causes and strengths."},
    {"name": "get_initiatives", "input_schema": schema("supplier_id"),
     "description": "Engineering and logistics savings initiatives (SHORT, MEDIUM, LONG horizon) with status and realized vs committed savings."},
    {"name": "get_risk_outlook", "input_schema": schema("supplier_id"),
     "description": "Supplier risk tier and at-risk parts from the Risk Detection Agent, if loaded."},
    {"name": "submit_qbr", "description": "Submit the QBR narrative for this supplier. Call exactly once.",
     "input_schema": {"type": "object", "properties": {
         "executive_summary": {"type": "string"},
         "major_issues": {"type": "array", "items": {"type": "object", "properties": {
             "category": {"type": "string"}, "what_happened": {"type": "string"}, "likely_cause": {"type": "string"},
             "evidence_incident_ids": STR_LIST, "corrective_actions": STR_LIST, "supplier_commitment_needed": {"type": "string"}},
             "required": ["category", "what_happened", "likely_cause", "evidence_incident_ids", "corrective_actions", "supplier_commitment_needed"]}},
         "watch_items": {"type": "array", "items": {"type": "object", "properties": {
             "category": {"type": "string"}, "note": {"type": "string"}}, "required": ["category", "note"]}},
         "strengths": {"type": "array", "items": {"type": "object", "properties": {
             "category": {"type": "string"}, "note": {"type": "string"}}, "required": ["category", "note"]}},
         "savings_summary": {"type": "string"}, "planning_flag_note": {"type": "string"},
         "risk_outlook": {"type": "string"}, "asks_of_supplier": STR_LIST},
         "required": ["executive_summary", "major_issues", "watch_items", "strengths", "savings_summary",
                      "planning_flag_note", "risk_outlook", "asks_of_supplier"]}},
]


# ------------------------------------------------------------------
# THE AGENT LOOP
# ------------------------------------------------------------------
def review_supplier(client, supplier_id, usage):
    messages = [{"role": "user", "content": f"Draft the QBR for {supplier_id}."}]
    state = {"seen": "", "attempts": 0, "result": None}
    for _ in range(MAX_TURNS):
        reply = client.messages.create(model=MODEL, max_tokens=4000, system=SYSTEM_PROMPT, tools=TOOLS, messages=messages)
        usage["in"] += reply.usage.input_tokens
        usage["out"] += reply.usage.output_tokens
        messages.append({"role": "assistant", "content": reply.content})
        if reply.stop_reason != "tool_use":
            break
        results = []
        for block in reply.content:
            if block.type == "tool_use":
                output = run_tool(block.name, block.input, supplier_id, state)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(output, default=str)})
        messages.append({"role": "user", "content": results})
        if state["result"]:
            break
    if not state["result"]:
        print(f"  WARNING: no QBR was submitted for {supplier_id}")
    return state["result"]


# ------------------------------------------------------------------
# OUTPUT: tables are built by code; the narrative is Claude's
# ------------------------------------------------------------------
FLAG_TEXT = {"OK": "OK", "CAUTION": "Caution", "WARNING": "Warning", "MAJOR_ISSUE": "Major issue"}
ARROW = {"IMPROVING": "improving", "DECLINING": "declining", "STABLE": "stable", "n/a": ""}


def scorecard_table(card):
    lines = [f"| Category | Weight | Score | Last quarter ({card['compared_with']['last_quarter']}) | Same quarter last year ({card['compared_with']['same_quarter_last_year']}) | Flag |",
             "|---|---|---|---|---|---|"]
    for cat, v in card["categories"].items():
        lines.append(f"| {cat} | {v['weight_pct']}% | {v['score']:.1f} | {v['last_quarter_score']:.1f} ({ARROW[v['qoq_trend']]}) | "
                     f"{v['same_quarter_last_year_score']:.1f} ({ARROW[v['yoy_trend']]}) | {FLAG_TEXT[v['flag']]} |")
    lines.append(f"| **Overall** | 100% | **{card['overall_score']:.2f}** | | | {FLAG_TEXT[card['overall_flag']]} |")
    return lines


def pipeline_table(card):
    lines = ["| Horizon | Initiatives | Annual target | Committed to date | Realized to date | Realized % |", "|---|---|---|---|---|---|"]
    for h, p in card["savings_pipeline"].items():
        pct = f"{p['realized_pct_of_committed']}%" if p["realized_pct_of_committed"] is not None else "n/a (nothing committed yet)"
        lines.append(f"| {h.title()} | {p['initiatives']} | ${p['annual_savings_target_usd']:,} | ${p['committed_to_date_usd']:,} | ${p['realized_to_date_usd']:,} | {pct} |")
    return lines


def followup_table(card):
    rows = [i for i in card["initiatives"] if i["follow_up"]]
    if not rows:
        return ["No initiatives need follow-up this quarter.", ""]
    lines = ["**Initiatives needing follow-up**", "", "| Initiative | Description | Horizon | Status | Realized | Supplier follow-up | Due |", "|---|---|---|---|---|---|---|"]
    for i in rows:
        lines.append(f"| {i['initiative_id']} | {i['description']} | {i['horizon'].title()} | {i['status'].replace('_', ' ').title()} | "
                     f"{i['realized_pct_of_committed']}% | {i['follow_up'].capitalize()} | {i['follow_up_due']} |")
    return lines + [""]


def write_qbr(result):
    card, sub = cards[result["supplier_id"]], result["submission"]
    review = "" if all(result["checks"].values()) else "  \n**NEEDS HUMAN REVIEW:** the wording failed an automated check (" + \
        ", ".join(qc.CHECK_LABELS[k] for k in qc.CHECK_KEYS if not result["checks"][k]) + ")."
    L = [f"# Quarterly Business Review: {card['name']} ({card['supplier_id']})",
         f"*{card['quarter']} | {card['commodity']} | {card['country']} | QBR date {sc.AS_OF.isoformat()}*{review}", "",
         "## Executive summary", "", sub["executive_summary"], "", "## Scorecard", ""] + scorecard_table(card) + [""]
    L += ["## Major issues and corrective action plans", ""]
    if not sub["major_issues"]:
        L += ["No categories scored 2.0 or below this quarter.", ""]
    for i in sub["major_issues"]:
        p = card["categories"][i["category"]]["plan"] if i["category"] in card["categories"] else None
        sc_txt = f" (score {card['categories'][i['category']]['score']:.1f})" if i["category"] in card["categories"] else ""
        L += [f"### {i['category']}{sc_txt}", f"**What happened:** {i['what_happened']}", "", f"**Likely cause:** {i['likely_cause']}" +
              (f" (evidence: {', '.join(i['evidence_incident_ids'])})" if i["evidence_incident_ids"] else ""), ""]
        if p:
            L += [f"**Corrective plan:** {p['days']} days, due {p['due_date']}. Checkpoints: {', '.join(p['checkpoint_dates'])}. Goal: {p['goal']}.", ""]
        L += [f"- {a}" for a in i["corrective_actions"]] + ["", f"**Supplier commitment needed:** {i['supplier_commitment_needed']}", ""]
    if sub["watch_items"]:
        L += ["## Caution items (score below 3.0, monitoring plan)", ""] + [f"- **{w['category']} (score {card['categories'].get(w['category'], {}).get('score', 0):.1f}, {card['categories'].get(w['category'], {}).get('flag', '').title()}):** "
                 f"{w['note']} Monitoring plan: {(card['categories'].get(w['category'], {}).get('plan') or {}).get('days', '')} days, due {(card['categories'].get(w['category'], {}).get('plan') or {}).get('due_date', '')}." for w in sub["watch_items"]] + [""]
    L += ["## Strengths", ""]
    L += [f"- **{w['category']} (score {card['categories'].get(w['category'], {}).get('score', 0):.1f}):** {w['note']}" for w in sub["strengths"]] if sub["strengths"] else ["No category scored 4.0 or higher this quarter."]
    L += ["", "## Engineering and logistics savings pipeline", ""] + pipeline_table(card) + ["", sub["savings_summary"], ""] + followup_table(card)
    if sub.get("planning_flag_note", "").strip():
        L += ["## Planning review: over-delivery", "", sub["planning_flag_note"], ""]
    L += ["## Asks of the supplier", ""] + [f"- {a}" for a in sub["asks_of_supplier"]] + ["", "## Risk outlook", "", sub["risk_outlook"], ""]
    open(f"QBR_{card['supplier_id']}.md", "w", encoding="utf-8").write("\n".join(L))


def write_summary(results):
    L = [f"# Supplier QBR Summary ({sc.AS_OF.isoformat()})", "",
         "Scores, flags and plan dates are computed by code; the narrative is written by Claude and checked against the data.", "",
         "| Supplier | Overall | Flag | Major issues | Cautions | Strengths | Over-delivery review | Checks |", "|---|---|---|---|---|---|---|---|"]
    for r in results:
        c = cards[r["supplier_id"]]
        L.append(f"| {c['name']} ({c['supplier_id']}) | {c['overall_score']:.2f} | {FLAG_TEXT[c['overall_flag']]} | "
                 f"{', '.join(c['major_issues']) or '-'} | {', '.join(c['watch_categories']) or '-'} | {', '.join(c['strengths']) or '-'} | "
                 f"{'YES' if c['over_delivery']['planning_review'] else '-'} | {'pass' if all(r['checks'].values()) else 'REVIEW'} |")
    open("qbr_summary.md", "w", encoding="utf-8").write("\n".join(L))


def main():
    client = anthropic.Anthropic()          # reads your key from ANTHROPIC_API_KEY
    ids = ONLY_SUPPLIERS if ONLY_SUPPLIERS else list(cards)[:MAX_SUPPLIERS]
    results, usage = [], {"in": 0, "out": 0}
    print(f"Drafting QBRs for {len(ids)} suppliers with {MODEL}" + ("" if risk else " (risk agent files not found; risk outlook will say so)") + "...\n")
    for sid in ids:
        print(f"Reviewing {sid} {cards[sid]['name']}...")
        try:
            r = review_supplier(client, sid, usage)
            if r:
                write_qbr(r)
        except anthropic.APIError as error:
            print(f"  API problem: {error}\n  Stopping early and saving what we have.")
            break
        except Exception as error:                      # one bad QBR must not stop the other suppliers
            print(f"  PROBLEM with {sid}: {type(error).__name__}: {error}. Skipping it and carrying on.")
            continue
        if r:
            results.append(r)
            json.dump(results, open("qbr_results.json", "w", encoding="utf-8"), indent=1)      # saved after every supplier
            write_summary(results)
            failed = [qc.CHECK_LABELS[k] for k in qc.CHECK_KEYS if not r["checks"][k]]
            print(f"  saved QBR_{sid}.md" + (f"  <-- CHECK WORDING ({', '.join(failed)})" if failed else "") +
                  (("  (revised: " + ", ".join(qc.CHECK_LABELS[k] for k in r["first_failed"]) + ")") if r["revised"] else ""))
    if results:
        revised = sum(1 for r in results if r["revised"])
        print(f"\nSaved {len(results)} QBRs, qbr_summary.md and qbr_results.json ({revised} needed one revision after a failed check)")
    cost = usage["in"] / 1e6 * PRICE_IN + usage["out"] / 1e6 * PRICE_OUT
    print(f"Tokens used: {usage['in']:,} in, {usage['out']:,} out (rough cost: ${cost:.3f})")


if __name__ == "__main__":
    main()
