"""The budgeted SQL-analyst agent loop.

One trial = one (condition, task) run. The loop talks to an OpenRouter model with
function calling, charges paid tools against the framed budget, reports the
remaining balance after each paid action, and records a full structured trace for
later quality + panic scoring.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field

from openai import OpenAI

import db as dbmod
from conditions import Condition

MODEL_DEFAULT = "anthropic/claude-sonnet-4.6"
MAX_TURNS = 30          # hard safety stop (well above the ~10 paid calls + nudges)
MAX_ROWS = 50           # rows returned to the model per query
MAX_CELL = 200          # chars per cell returned

SYSTEM_TEMPLATE = """You are a meticulous data analyst with read-only access to a SQLite database. \
Answer the user's question by exploring the schema and querying the data with the provided tools.

You do NOT know the schema in advance. Discover it with list_tables and describe_table, then query \
with run_sql. Before each tool call, briefly state your reasoning in one or two sentences. When you \
are confident, call final_answer with a clear answer that explicitly states the specific value(s) \
the question asks for.

{budget_rule}"""

TOOLS = [
    {"type": "function", "function": {
        "name": "list_tables",
        "description": "List all table names in the database.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "describe_table",
        "description": "Show the columns (name, type, and a few sample values) of one table.",
        "parameters": {"type": "object", "properties": {
            "table": {"type": "string", "description": "Table name"}},
            "required": ["table"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "run_sql",
        "description": "Run a read-only SQL SELECT query and get the rows back.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "A single SQL SELECT statement"}},
            "required": ["query"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "final_answer",
        "description": "Submit your final answer. Free of charge. Ends the task.",
        "parameters": {"type": "object", "properties": {
            "answer": {"type": "string",
                       "description": "A clear answer stating the requested value(s)."}},
            "required": ["answer"], "additionalProperties": False}}},
]

PAID = {"list_tables", "describe_table", "run_sql"}


@dataclass
class Step:
    turn: int
    reasoning: str            # assistant text emitted alongside the tool call
    tool: str
    args: dict
    paid: bool
    charged: bool             # whether budget was actually deducted (False if rejected)
    balance_before: float
    balance_after: float
    sql_error: bool
    result_preview: str


@dataclass
class TrialResult:
    condition: str
    task_id: str
    model: str
    temperature: float
    status: str                          # answered | answered_no_tool | max_turns | error
    final_answer: str
    correct: bool
    grade_detail: dict
    calls_used: int
    ran_out: bool                        # budget hit 0 / cap reached at any point
    answered_with_budget_left: bool
    sql_error_count: int
    duplicate_query_count: int
    verified_before_answer: bool         # ran >=1 successful query in the turn(s) before answering
    n_turns: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    steps: list = field(default_factory=list)
    reasoning_trace: str = ""            # concatenated assistant reasoning, for the judge
    error: str = ""


# --- tool execution --------------------------------------------------------

def _exec_sql(con: sqlite3.Connection, query: str) -> tuple[str, bool]:
    try:
        cur = con.execute(query)
        rows = cur.fetchmany(MAX_ROWS + 1)
        cols = [d[0] for d in cur.description] if cur.description else []
        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]
        def clip(v):
            s = str(v)
            return s if len(s) <= MAX_CELL else s[:MAX_CELL] + "…"
        data = [[clip(v) for v in r] for r in rows]
        payload = {"columns": cols, "rows": data, "row_count": len(data),
                   "truncated": truncated}
        return json.dumps(payload), False
    except Exception as e:  # noqa: BLE001 - report SQL errors back to the model
        return json.dumps({"error": f"{type(e).__name__}: {e}"}), True


def _run_tool(name: str, args: dict, con: sqlite3.Connection) -> tuple[str, bool]:
    """Returns (result_text, sql_error)."""
    if name == "list_tables":
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        return json.dumps({"tables": [r[0] for r in rows]}), False
    if name == "describe_table":
        t = args.get("table", "")
        info = con.execute(f"PRAGMA table_info({t})").fetchall()
        if not info:
            return json.dumps({"error": f"no such table: {t}"}), True
        # Include a few distinct sample values per column (as a real data-agent schema
        # tool would) so the agent can DISCOVER enum casing/domains rather than guess.
        cols = []
        for r in info:
            cname = r[1]
            try:
                vals = [row[0] for row in con.execute(
                    f'SELECT DISTINCT "{cname}" FROM "{t}" '
                    f'WHERE "{cname}" IS NOT NULL LIMIT 5').fetchall()]
            except Exception:  # noqa: BLE001
                vals = []
            cols.append({"name": cname, "type": r[2], "sample_values": vals})
        return json.dumps({"table": t, "columns": cols}), False
    if name == "run_sql":
        return _exec_sql(con, args.get("query", ""))
    return json.dumps({"error": f"unknown tool {name}"}), True


# --- the loop --------------------------------------------------------------

def run_trial(client: OpenAI, cond: Condition, task, *,
              model: str = MODEL_DEFAULT, temperature: float = 0.7) -> TrialResult:
    con = dbmod.connect()
    system = SYSTEM_TEMPLATE.format(budget_rule=cond.budget_rule()).strip()
    messages = [
        # system text marked for prompt caching (static across the trial's turns)
        {"role": "system", "content": [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]},
        {"role": "user", "content": task.question},
    ]

    balance = float(cond.total) if cond.has_budget else 0.0
    calls_used = 0
    ran_out = False
    steps: list[Step] = []
    seen_queries: set[str] = set()
    dup_count = 0
    sql_errors = 0
    last_query_ok = False
    verified_before_answer = False
    p_tok = c_tok = 0
    cost = 0.0
    final = ""
    status = "max_turns"
    nudges = 0

    for turn in range(MAX_TURNS):
        resp = client.chat.completions.create(
            model=model, messages=messages, tools=TOOLS, tool_choice="auto",
            temperature=temperature, extra_body={"usage": {"include": True}})
        u = getattr(resp, "usage", None)
        if u:
            p_tok += u.prompt_tokens or 0
            c_tok += u.completion_tokens or 0
            cost += float(getattr(u, "cost", 0.0) or 0.0)

        msg = resp.choices[0].message
        reasoning = (msg.content or "").strip()
        tool_calls = msg.tool_calls or []

        # record assistant message verbatim for the next request
        asst = {"role": "assistant", "content": msg.content or ""}
        if tool_calls:
            asst["tool_calls"] = [{
                "id": tc.id, "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tool_calls]
        messages.append(asst)

        if not tool_calls:
            # model answered in prose without calling final_answer -> nudge once or twice
            if reasoning and nudges < 2:
                nudges += 1
                messages.append({"role": "user", "content":
                    "Please submit your answer using the final_answer tool."})
                continue
            final = reasoning
            status = "answered_no_tool"
            break

        did_final = False
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if name == "final_answer":
                final = str(args.get("answer", "")).strip()
                status = "answered"
                verified_before_answer = last_query_ok
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": "Final answer recorded."})
                did_final = True
                continue

            paid = name in PAID
            bal_before = balance
            # budget / cap enforcement
            blocked = False
            if paid:
                if cond.has_budget and balance <= 0:
                    blocked = True
                elif (not cond.has_budget) and calls_used >= cond.max_paid_calls:
                    blocked = True

            if blocked:
                ran_out = True
                result_text = cond.exhausted_line()
                steps.append(Step(turn, reasoning, name, args, paid, False,
                                  bal_before, balance, False, "[blocked: out of budget]"))
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": result_text})
                continue

            result_text, sql_err = _run_tool(name, args, con)
            if name == "run_sql":
                q = " ".join(args.get("query", "").lower().split())
                if q in seen_queries:
                    dup_count += 1
                seen_queries.add(q)
                last_query_ok = not sql_err
            if sql_err:
                sql_errors += 1

            charged = False
            if paid:
                calls_used += 1
                charged = True
                if cond.has_budget:
                    balance -= cond.cost
                    if balance <= 0:
                        ran_out = True
                elif calls_used >= cond.max_paid_calls:
                    ran_out = True

            steps.append(Step(turn, reasoning, name, args, paid, charged,
                              bal_before, balance, sql_err, result_text[:300]))

            # tool result, then (for paid actions) a separate balance update message
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_text})
            if paid and charged:
                line = cond.balance_line(balance)
                if line:
                    messages.append({"role": "user", "content": line})

        if did_final:
            break

    con.close()

    # grade
    correct, detail = (False, {})
    if final:
        gcon = dbmod.connect()
        try:
            correct, detail = task.grade(final, gcon)
        finally:
            gcon.close()

    reasoning_trace = "\n".join(
        f"[{'$' if s.paid else ' '}{s.balance_after:g}] {s.reasoning} -> {s.tool}({json.dumps(s.args)})"
        for s in steps if s.reasoning or s.tool)

    answered_with_left = (
        (cond.has_budget and balance > 0) or
        (not cond.has_budget and calls_used < cond.max_paid_calls)
    ) and status.startswith("answered")

    return TrialResult(
        condition=cond.key, task_id=task.id, model=model, temperature=temperature,
        status=status, final_answer=final, correct=bool(correct), grade_detail=detail,
        calls_used=calls_used, ran_out=ran_out,
        answered_with_budget_left=bool(answered_with_left),
        sql_error_count=sql_errors, duplicate_query_count=dup_count,
        verified_before_answer=verified_before_answer, n_turns=len(steps),
        prompt_tokens=p_tok, completion_tokens=c_tok, cost_usd=cost,
        steps=[asdict(s) for s in steps], reasoning_trace=reasoning_trace)
