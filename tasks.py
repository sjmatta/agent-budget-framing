"""Task bank: analytical questions with exact ground truth + deterministic graders.

Each task's gold answer is computed by running gold SQL against the deterministic
DB, so grading never depends on an LLM. Graders parse the agent's free-text final
answer and require every required component (a name and/or a number) to be present
and, for numbers, within tolerance. "Revenue" is defined throughout as
SUM(quantity * unit_price) over order_items, restricted to completed orders.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Callable

import db as dbmod

# --- answer parsing helpers ------------------------------------------------

_NUM_RE = re.compile(r"-?\$?\s*\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\$?\s*\d+(?:\.\d+)?")


def extract_numbers(text: str) -> list[float]:
    out = []
    for m in _NUM_RE.findall(text or ""):
        s = m.replace(",", "").replace("$", "").replace(" ", "")
        try:
            out.append(float(s))
        except ValueError:
            pass
    return out


def has_number(text: str, target: float, atol: float = 0.0, rtol: float = 0.005) -> bool:
    for x in extract_numbers(text):
        if abs(x - target) <= atol or abs(x - target) <= rtol * abs(target):
            return True
    return False


def has_text(text: str, target: str) -> bool:
    return target.lower() in (text or "").lower()


# --- task definition -------------------------------------------------------

@dataclass
class Task:
    id: str
    difficulty: str
    question: str
    gold_sql: str          # returns one row; documents the intended computation
    _grade: Callable[[str, sqlite3.Connection], tuple[bool, dict]]

    def gold(self, con: sqlite3.Connection) -> sqlite3.Row:
        return con.execute(self.gold_sql).fetchone()

    def grade(self, answer: str, con: sqlite3.Connection) -> tuple[bool, dict]:
        return self._grade(answer, con)


REVENUE = "SUM(oi.quantity * oi.unit_price)"
COMPLETED_JOIN = (
    "FROM order_items oi "
    "JOIN orders o ON o.order_id = oi.order_id "
    "WHERE o.status = 'completed'"
)


def _t1(answer, con):
    rows = con.execute(
        f"SELECT c.name AS cat, {REVENUE} AS rev "
        "FROM order_items oi "
        "JOIN orders o ON o.order_id = oi.order_id "
        "JOIN products p ON p.product_id = oi.product_id "
        "JOIN categories c ON c.category_id = p.category_id "
        "WHERE o.status = 'completed' "
        "GROUP BY c.category_id ORDER BY rev DESC"
    ).fetchall()
    total = sum(r["rev"] for r in rows)
    top = rows[0]
    pct = round(100 * top["rev"] / total, 1)
    ok_name = has_text(answer, top["cat"])
    ok_pct = has_number(answer, pct, atol=0.15)
    return (ok_name and ok_pct), {"gold_cat": top["cat"], "gold_pct": pct,
                                  "ok_name": ok_name, "ok_pct": ok_pct}


def _t2(answer, con):
    rev = con.execute(
        f"SELECT {REVENUE} AS rev "
        "FROM order_items oi "
        "JOIN orders o ON o.order_id = oi.order_id "
        "JOIN customers cu ON cu.customer_id = o.customer_id "
        "WHERE o.status='completed' AND cu.country='Germany'"
    ).fetchone()["rev"]
    cnt = con.execute(
        "SELECT COUNT(DISTINCT o.customer_id) AS n "
        "FROM orders o JOIN customers cu ON cu.customer_id=o.customer_id "
        "WHERE o.status='completed' AND cu.country='Germany'"
    ).fetchone()["n"]
    rev = round(rev, 2)
    ok_rev = has_number(answer, rev, rtol=0.01)
    ok_cnt = has_number(answer, cnt, atol=0.5)
    return (ok_rev and ok_cnt), {"gold_rev": rev, "gold_cnt": cnt,
                                 "ok_rev": ok_rev, "ok_cnt": ok_cnt}


def _t3(answer, con):
    row = con.execute(
        f"SELECT cu.name AS nm, {REVENUE} AS spend "
        "FROM order_items oi "
        "JOIN orders o ON o.order_id=oi.order_id "
        "JOIN customers cu ON cu.customer_id=o.customer_id "
        "WHERE o.status='completed' "
        "GROUP BY o.customer_id ORDER BY spend DESC LIMIT 1"
    ).fetchone()
    spend = round(row["spend"], 2)
    ok_name = has_text(answer, row["nm"])
    ok_spend = has_number(answer, spend, rtol=0.01)
    return (ok_name and ok_spend), {"gold_name": row["nm"], "gold_spend": spend,
                                    "ok_name": ok_name, "ok_spend": ok_spend}


def _t4(answer, con):
    row = con.execute(
        f"SELECT substr(o.order_date,1,7) AS ym, {REVENUE} AS rev "
        "FROM order_items oi JOIN orders o ON o.order_id=oi.order_id "
        "WHERE o.status='completed' "
        "GROUP BY ym ORDER BY rev DESC LIMIT 1"
    ).fetchone()
    rev = round(row["rev"], 2)
    ok_ym = has_text(answer, row["ym"])
    ok_rev = has_number(answer, rev, rtol=0.01)
    return (ok_ym and ok_rev), {"gold_ym": row["ym"], "gold_rev": rev,
                                "ok_ym": ok_ym, "ok_rev": ok_rev}


TASKS: list[Task] = [
    Task("cat_revenue", "medium",
         "Considering only completed orders, which product category produced the "
         "most revenue, and what percentage of total completed-order revenue does it "
         "represent? Give the category name and the percentage rounded to one decimal place.",
         "SELECT 1", _t1),
    Task("germany", "medium",
         "Considering only completed orders, what is the total revenue generated by "
         "customers from Germany, and how many distinct German customers placed at "
         "least one completed order? Give revenue to 2 decimal places and the customer count.",
         "SELECT 1", _t2),
    Task("top_customer", "medium",
         "Among completed orders only, which customer spent the most in total? Give the "
         "customer's full name and their total spend to 2 decimal places.",
         "SELECT 1", _t3),
    Task("top_month", "hard",
         "Considering only completed orders, which calendar month of 2025 (formatted as "
         "YYYY-MM) had the highest total revenue, and what was that revenue to 2 decimal places?",
         "SELECT 1", _t4),
]

TASKS_BY_ID = {t.id: t for t in TASKS}


if __name__ == "__main__":
    con = dbmod.connect()
    for t in TASKS:
        # exercise grader on a deliberately-correct synthetic answer
        if t.id == "cat_revenue":
            _, d = t.grade("", con); ans = f"{d['gold_cat']} with {d['gold_pct']}%"
        elif t.id == "germany":
            _, d = t.grade("", con); ans = f"revenue ${d['gold_rev']:,.2f}, {d['gold_cnt']} customers"
        elif t.id == "top_customer":
            _, d = t.grade("", con); ans = f"{d['gold_name']} spent ${d['gold_spend']:,.2f}"
        else:
            _, d = t.grade("", con); ans = f"{d['gold_ym']} with ${d['gold_rev']:,.2f}"
        ok, det = t.grade(ans, con)
        print(f"[{t.difficulty:6s}] {t.id:13s} gold={det} -> grader_on_gold={ok}")
    con.close()
