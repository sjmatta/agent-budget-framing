"""Experiment 2 analysis: decompose WHY doubloons helped.

(1) Currency-property regression — code each label on independent dimensions
    (whimsy, concreteness/countability, valence, verbosity) and regress correctness
    on the dimensions to see which property carries the effect.
(2) Tone probe — noun fixed (doubloons), vary running-low message tone
    (neutral / urgent / playful): isolates stakes/threat framing from the noun.
(3) Replication of the doubloons class (gold coins / gems) vs. neutral baseline.

Usage: uv run python analyze_panel.py [--glob runs/panel.jsonl] [--model-tag panel]
"""

from __future__ import annotations

import argparse
import glob
import json

import numpy as np
import pandas as pd
from scipy import stats

# dimension coding for the currency-property panel (tone variants excluded here)
# whimsy: playful/fantastical token; concrete: a countable physical object;
# valence: +1 positive/playful, 0 neutral, -1 threatening; verbose: multi-word label
DIMS = {
    "credits":   dict(whimsy=0, concrete=0, valence=0,  verbose=0),
    "tokens":    dict(whimsy=0, concrete=1, valence=0,  verbose=0),
    "money":     dict(whimsy=0, concrete=1, valence=0,  verbose=0),  # $ = transactional/neutral-stakes
    "dubloons":  dict(whimsy=1, concrete=1, valence=1,  verbose=0),
    "goldcoins": dict(whimsy=1, concrete=1, valence=1,  verbose=0),
    "gems":      dict(whimsy=1, concrete=1, valence=1,  verbose=0),
    "latinum":   dict(whimsy=1, concrete=1, valence=1,  verbose=1),
    "lives":     dict(whimsy=0, concrete=1, valence=-1, verbose=0),
}
TONE = {"dubloons": "neutral", "dub_urgent": "urgent", "dub_playful": "playful"}


def load(pattern: str) -> pd.DataFrame:
    rows = []
    for f in glob.glob(pattern):
        for line in open(f):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("status") == "error":
                continue
            rows.append({"condition": r["condition"], "task_id": r["task_id"],
                         "correct": int(r["correct"]), "calls": r["calls_used"],
                         "ran_out": int(r["ran_out"]), "panic": r["panic_score"]})
    return pd.DataFrame(rows)


def tw(df, cond):
    sub = df[df.condition == cond]
    return sub.groupby("task_id")["correct"].mean().mean() if len(sub) else np.nan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="runs/panel.jsonl")
    args = ap.parse_args()
    df = load(args.glob)
    feas = df[df.task_id != "cat_revenue"]
    import statsmodels.formula.api as smf

    print(f"loaded {len(df)} trials, {df.condition.nunique()} conditions\n")

    # --- equal-task-weighted correctness, ranked ---
    print("=== equal-task-weighted correctness (3 feasible tasks) ===")
    order = sorted(df.condition.unique(), key=lambda c: -tw(feas, c))
    for c in order:
        print(f"  {c:12s} {tw(feas,c):.3f}  (panic {df[df.condition==c].panic.mean():.3f}, "
              f"ran_out {df[df.condition==c].ran_out.mean():.2f})")

    # --- (1) currency-property regression ---
    print("\n=== (1) Currency-property logistic regression ===")
    cur = feas[feas.condition.isin(DIMS)].copy()
    for d in ["whimsy", "concrete", "valence", "verbose"]:
        cur[d] = cur.condition.map(lambda c: DIMS[c][d])
    cur["correct"] = cur.correct.astype(int)
    m = smf.logit("correct ~ whimsy + concrete + valence + verbose + C(task_id)",
                  data=cur).fit(disp=0)
    print("  (correct ~ whimsy + concrete + valence + verbose + task)")
    for name in ["whimsy", "concrete", "valence", "verbose"]:
        if name in m.params:
            print(f"    {name:9s} OR={np.exp(m.params[name]):5.2f}  "
                  f"coef={m.params[name]:+.2f}  p={m.pvalues[name]:.4f}")

    # --- replication: doubloons-class vs neutral baselines ---
    print("\n=== Whimsy-class replication (vs neutral 'credits') ===")
    base = feas[feas.condition == "credits"]["correct"]
    for c in ["dubloons", "goldcoins", "gems"]:
        x = feas[feas.condition == c]["correct"]
        _, p = stats.fisher_exact([[x.sum(), len(x) - x.sum()],
                                   [base.sum(), len(base) - base.sum()]])
        print(f"  {c:10s} {tw(feas,c):.3f} vs credits {tw(feas,'credits'):.3f}  "
              f"(pooled {x.mean():.2f} vs {base.mean():.2f}, Fisher p={p:.4f})")

    # --- (2) tone probe ---
    print("\n=== (2) Tone probe — noun fixed (doubloons), vary running-low tone ===")
    for c in ["dubloons", "dub_urgent", "dub_playful"]:
        sub = df[df.condition == c]
        print(f"  {TONE[c]:8s} ({c:11s}) correct(tw)={tw(feas,c):.3f}  "
              f"panic={sub.panic.mean():.3f}  ran_out={sub.ran_out.mean():.2f}  n={len(sub)}")
    # urgent vs playful panic + correctness
    for a, b in [("dub_urgent", "dub_playful"), ("dub_urgent", "dubloons")]:
        pa = df[df.condition == a].panic.values
        pb = df[df.condition == b].panic.values
        _, pp = stats.mannwhitneyu(pa, pb, alternative="two-sided")
        ca = feas[feas.condition == a]["correct"]; cb = feas[feas.condition == b]["correct"]
        _, pc = stats.fisher_exact([[ca.sum(), len(ca)-ca.sum()], [cb.sum(), len(cb)-cb.sum()]])
        print(f"  {a} vs {b}: panic Δ={pa.mean()-pb.mean():+.3f} (p={pp:.3f}); "
              f"correct Δ={ca.mean()-cb.mean():+.3f} (p={pc:.3f})")


if __name__ == "__main__":
    main()
