"""Experiment 3: time-units AS currency.

Mechanics are identical across seconds/minutes/hours (5 paid calls, 1/call) — the
ONLY thing that differs is the unit's *implied duration* (5s feels frantic, 5h feels
loose). Question: does felt-duration move behavior even though the real constraint
never changes? Tests the "LLMs have a bad sense of time" intuition.

Runs on the FIXED describe_table (sample values exposed), so it also confirms the
casing artifact is gone: correctness should sit near ceiling and the real signal
shifts to panic + efficiency.

Usage: uv run python analyze_time.py --glob runs/exp3_time.jsonl
"""

from __future__ import annotations

import argparse
import glob
import json

import numpy as np
import pandas as pd
from scipy import stats

FEASIBLE = {"germany", "top_customer", "top_month"}
# implied-duration rank: seconds (tight) < minutes < hours (loose)
MAGNITUDE = {"seconds": 0, "minutes": 1, "hours": 2}
TIME_UNITS = ["seconds", "minutes", "hours"]
CURRENCY = ["credits", "money", "dubloons"]


def casing_of(steps):
    import re
    q = " ".join(s["args"].get("query", "") for s in steps if s["tool"] == "run_sql")
    if re.search(r"lower\(|upper\(", q, re.I):
        return "case_insensitive"
    if "'completed'" in q:
        return "lower"
    if "'Completed'" in q:
        return "Title"
    return "other"


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
                "calls": r["calls_used"], "ran_out": int(r["ran_out"]),
                "left_over": int(r["answered_with_budget_left"]),
                "verified": int(r["verified_before_answer"]),
                "casing": casing_of(r["steps"]),
            })
    return pd.DataFrame(rows)


def tw(df, cond, col="correct"):
    sub = df[df.condition == cond]
    return sub.groupby("task_id")[col].mean().mean() if len(sub) else np.nan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="runs/exp3_time.jsonl")
    args = ap.parse_args()
    df = load(args.glob)
    print(f"loaded {len(df)} feasible-task trials\n")

    # 0. confirmatory: casing artifact gone?
    print("=== 0. Casing distribution (confirm fix: agents should now use lower/insensitive) ===")
    print(df.casing.value_counts().to_string())
    print(f"  correctness pooled: {df.correct.mean():.3f}\n")

    # 1. per-condition table
    print("=== 1. Per-condition (equal-task-weighted correctness; pooled panic/efficiency) ===")
    print(f"  {'cond':10s} {'correct':>7s} {'panic':>6s} {'calls':>6s} {'ranout':>7s} {'leftovr':>8s}  n")
    for c in sorted(df.condition.unique(), key=lambda c: (MAGNITUDE.get(c, -1), c)):
        s = df[df.condition == c]
        print(f"  {c:10s} {tw(df,c):7.3f} {s.panic.mean():6.3f} {s.calls.mean():6.2f} "
              f"{s.ran_out.mean():7.2f} {s.left_over.mean():8.2f}  {len(s)}")

    # 2. felt-duration effect WITHIN time units (the core test)
    tu = df[df.condition.isin(TIME_UNITS)].copy()
    if tu.condition.nunique() >= 2:
        print("\n=== 2. Felt-duration effect across time units (seconds<minutes<hours) ===")
        groups = [tu[tu.condition == c]["panic"].values for c in TIME_UNITS
                  if (tu.condition == c).sum() > 0]
        if len(groups) >= 2:
            h, p = stats.kruskal(*groups)
            print(f"  Kruskal-Wallis on panic across units: H={h:.2f}, p={p:.3f}")
        tu["mag"] = tu.condition.map(MAGNITUDE)
        rho, pr = stats.spearmanr(tu["mag"], tu["panic"])
        print(f"  Spearman(magnitude, panic): rho={rho:+.3f}, p={pr:.3f} "
              f"(neg => tighter unit 'seconds' panics more)")
        rho2, pr2 = stats.spearmanr(tu["mag"], tu["calls"])
        print(f"  Spearman(magnitude, calls): rho={rho2:+.3f}, p={pr2:.3f}")
        if (tu.condition == "seconds").any() and (tu.condition == "hours").any():
            a = tu[tu.condition == "seconds"]["panic"].values
            b = tu[tu.condition == "hours"]["panic"].values
            _, pmw = stats.mannwhitneyu(a, b, alternative="two-sided")
            print(f"  seconds vs hours panic: {a.mean():.3f} vs {b.mean():.3f} "
                  f"(Δ={a.mean()-b.mean():+.3f}, MWU p={pmw:.3f})")

    # 3. time-units vs currency baselines (panic + efficiency)
    print("\n=== 3. Time-units vs currency framings (pooled) ===")
    t = df[df.condition.isin(TIME_UNITS)]
    cur = df[df.condition.isin(CURRENCY)]
    if len(t) and len(cur):
        _, p = stats.mannwhitneyu(t.panic.values, cur.panic.values, alternative="two-sided")
        print(f"  panic  time {t.panic.mean():.3f} vs currency {cur.panic.mean():.3f} (MWU p={p:.3f})")
        print(f"  calls  time {t.calls.mean():.2f} vs currency {cur.calls.mean():.2f}")
        print(f"  ranout time {t.ran_out.mean():.2f} vs currency {cur.ran_out.mean():.2f}")


if __name__ == "__main__":
    main()
