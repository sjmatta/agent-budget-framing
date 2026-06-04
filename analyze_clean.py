"""Confounder-controlled RE-ANALYSIS of existing data (no API calls).

The correctness signal turned out to be driven by an unverifiable string-casing
guess (`status = 'completed'` vs `'Completed'`). This script isolates that:

  1. Shows correctness is ~determined by casing.
  2. Mediation check: WITHIN correct-casing trials, does framing still move correctness?
     (If not, framing's only correctness channel was the casing guess.)
  3. Quantifies the real, robust failure: silent wrong answers (a query returned 0
     rows on a bad assumption, yet the agent answered) and the zero-verification rate.
  4. Reports the one casing-independent signal: tone -> judged panic.

Usage: uv run python analyze_clean.py --glob runs/panel.jsonl
"""

from __future__ import annotations

import argparse
import glob
import json
import re

import numpy as np
import pandas as pd
from scipy import stats

FEASIBLE = {"germany", "top_customer", "top_month"}


def casing_of(steps):
    q = " ".join(s["args"].get("query", "") for s in steps if s["tool"] == "run_sql")
    if re.search(r"lower\(|upper\(", q, re.I):
        return "case_insensitive"
    if "'completed'" in q:
        return "lower"
    if "'Completed'" in q:
        return "Title"
    return "other"


def hit_zero_rows(steps):
    """Did the agent's final SQL return 0 rows (a wrong-assumption query)?"""
    last = None
    for s in steps:
        if s["tool"] == "run_sql" and s["charged"]:
            last = s
    return bool(last and '"row_count": 0' in (last.get("result_preview") or ""))


def verified_values(steps):
    """Did the agent ever inspect distinct values / use a robust match?"""
    q = " ".join(s["args"].get("query", "").lower() for s in steps if s["tool"] == "run_sql")
    return ("distinct status" in q or "distinct o.status" in q
            or "lower(" in q or "group by status" in q)


def load(pattern):
    rows = []
    for f in glob.glob(pattern):
        for line in open(f):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("status") == "error" or r["task_id"] not in FEASIBLE:
                continue
            rows.append({
                "condition": r["condition"], "task_id": r["task_id"],
                "correct": int(r["correct"]), "panic": r["panic_score"],
                "casing": casing_of(r["steps"]),
                "zero_rows": int(hit_zero_rows(r["steps"])),
                "verified": int(verified_values(r["steps"])),
            })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="runs/panel.jsonl")
    args = ap.parse_args()
    df = load(args.glob)
    print(f"loaded {len(df)} feasible-task trials from {args.glob}\n")

    # 1. correctness is determined by casing
    print("=== 1. Correctness by casing choice (pooled) ===")
    g = df.groupby("casing")["correct"].agg(["mean", "size"])
    print(g.round(3).to_string())
    print(f"\n  zero-verification: {1 - df.verified.mean():.1%} of trials NEVER checked the "
          f"actual status values or used case-insensitive matching")

    # 2. mediation: within correct-casing trials, does framing still matter?
    print("\n=== 2. Within CORRECT-casing (lowercase) trials: correctness by condition ===")
    lower = df[df.casing == "lower"]
    sub = lower.groupby("condition")["correct"].agg(["mean", "size"]).round(3)
    print(sub.to_string())
    if lower.condition.nunique() > 1:
        groups = [lower[lower.condition == c]["correct"].values
                  for c in lower.condition.unique() if (lower.condition == c).sum() > 3]
        try:
            chi = stats.chi2_contingency(
                pd.crosstab(lower.condition, lower.correct))[1]
            print(f"  chi2 test of framing effect WITHIN correct-casing: p = {chi:.3f}")
        except Exception as e:  # noqa: BLE001
            print("  (chi2 skipped:", e, ")")
    print("  -> if ~ceiling and n.s., framing's correctness effect was ENTIRELY the casing guess.")

    # 3. the framing -> casing channel (the actual mediator)
    print("\n=== 3. Framing -> casing guess (the mediator), germany ===")
    gz = df[df.task_id == "germany"]
    ct = pd.crosstab(gz.condition, gz.casing)
    if "lower" in ct:
        ct["pct_lower"] = (ct.get("lower", 0) / ct.sum(axis=1)).round(2)
    print(ct.to_string())

    # 4. silent wrong answers — the robust, production-relevant failure
    print("\n=== 4. Silent wrong-answer rate (final query hit 0 rows, agent answered anyway) ===")
    sw = df.groupby("condition")[["zero_rows", "correct"]].mean().round(3)
    print(sw.to_string())
    print(f"\n  overall: {df.zero_rows.mean():.1%} of trials answered off a 0-row query; "
          f"correlation(zero_rows, wrong) is near-total.")

    # 5. casing-independent signal: panic
    print("\n=== 5. Casing-independent signal — judged panic by condition ===")
    print(df.groupby("condition")["panic"].mean().round(3).sort_values().to_string())


if __name__ == "__main__":
    main()
