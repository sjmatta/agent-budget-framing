"""Analysis: load all run files, compute per-condition stats, run the planned
tests, make plots, and print a verdict on each hypothesis.

Usage: uv run python analyze.py [--glob 'runs/*.jsonl'] [--out results]
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

CONDITION_ORDER = ["control", "credits", "money", "time", "dubloons", "latinum"]
BASELINE = "credits"  # neutral-unit reference for contrasts


def load(patterns: list[str]) -> pd.DataFrame:
    rows = []
    for pat in patterns:
        for f in glob.glob(pat):
            with open(f) as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if r.get("status") == "error":
                        continue
                    pr = r.get("proxies", {})
                    rows.append({
                        "condition": r["condition"], "task_id": r["task_id"],
                        "correct": int(r["correct"]), "calls_used": r["calls_used"],
                        "ran_out": int(r["ran_out"]),
                        "answered_with_budget_left": int(r.get("answered_with_budget_left", 0)),
                        "panic": r["panic_score"],
                        "sql_errors": pr.get("sql_error_count", r.get("sql_error_count", 0)),
                        "dups": pr.get("duplicate_query_count", 0),
                        "verified": int(pr.get("verified_before_answer", 0)),
                        "err_rate_2nd_half": pr.get("err_rate_second_half", 0.0),
                        "reasoning_chars": pr.get("reasoning_chars", 0),
                        "cost": r.get("total_cost", 0.0),
                    })
    df = pd.DataFrame(rows)
    df["condition"] = pd.Categorical(df["condition"], CONDITION_ORDER, ordered=True)
    return df.sort_values("condition")


def ci95_mean(x):
    x = np.asarray(x, float)
    if len(x) < 2:
        return (np.nan, np.nan)
    se = x.std(ddof=1) / np.sqrt(len(x))
    h = se * stats.t.ppf(0.975, len(x) - 1)
    return (x.mean() - h, x.mean() + h)


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    d = 1 + z**2 / n
    c = p + z**2 / (2 * n)
    h = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return ((c - h) / d, (c + h) / d)


def cliffs_delta(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) == 0 or len(b) == 0:
        return np.nan
    gt = sum((a[:, None] > b[None, :]).sum(axis=1))
    lt = sum((a[:, None] < b[None, :]).sum(axis=1))
    return (gt - lt) / (len(a) * len(b))


def summary_table(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("condition", observed=True)
    out = pd.DataFrame({
        "n": g.size(),
        "correct_rate": g["correct"].mean(),
        "panic_mean": g["panic"].mean(),
        "calls_mean": g["calls_used"].mean(),
        "ran_out_rate": g["ran_out"].mean(),
        "sql_err_mean": g["sql_errors"].mean(),
        "verified_rate": g["verified"].mean(),
    })
    cl, cu, pl, pu = [], [], [], []
    for c in out.index:
        sub = df[df.condition == c]
        lo, hi = wilson(sub.correct.sum(), len(sub)); cl.append(lo); cu.append(hi)
        lo, hi = ci95_mean(sub.panic); pl.append(lo); pu.append(hi)
    out["correct_lo"], out["correct_hi"] = cl, cu
    out["panic_lo"], out["panic_hi"] = pl, pu
    return out.round(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", nargs="+", default=["runs/pilot.jsonl", "runs/full.jsonl"])
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    outdir = Path(args.out); outdir.mkdir(exist_ok=True)

    df = load(args.glob)
    if df.empty:
        print("no data found for", args.glob); return
    df.to_csv(outdir / "trials.csv", index=False)
    print(f"loaded {len(df)} trials across {df.condition.nunique()} conditions, "
          f"{df.task_id.nunique()} tasks; total cost ${df.cost.sum():.2f}\n")

    summ = summary_table(df)
    print("=== Per-condition summary ===")
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(summ.to_string())
    summ.to_csv(outdir / "summary.csv")

    # --- omnibus tests ---
    print("\n=== Omnibus tests across conditions ===")
    groups_panic = [df[df.condition == c].panic.values for c in CONDITION_ORDER if (df.condition == c).any()]
    if len(groups_panic) > 1 and all(len(g) > 0 for g in groups_panic):
        H, p = stats.kruskal(*groups_panic)
        print(f"Panic ~ condition: Kruskal-Wallis H={H:.2f}, p={p:.4f}")
    ct = pd.crosstab(df.condition, df.correct)
    if ct.shape[1] == 2 and (ct.values.sum(axis=1) > 0).all():
        chi2, pc, _, _ = stats.chi2_contingency(ct)
        print(f"Correct ~ condition: chi2={chi2:.2f}, p={pc:.4f}")

    # --- planned contrasts vs neutral baseline ---
    print(f"\n=== Pairwise contrasts vs '{BASELINE}' (Holm-corrected) ===")
    base_p = df[df.condition == BASELINE].panic.values
    base_c = df[df.condition == BASELINE].correct.values
    rows = []
    for c in CONDITION_ORDER:
        if c == BASELINE or not (df.condition == c).any():
            continue
        cp = df[df.condition == c].panic.values
        cc = df[df.condition == c].correct.values
        try:
            _, p_panic = stats.mannwhitneyu(cp, base_p, alternative="two-sided")
        except ValueError:
            p_panic = np.nan
        delta = cliffs_delta(cp, base_p)
        try:
            _, p_corr = stats.fisher_exact([[cc.sum(), len(cc) - cc.sum()],
                                            [base_c.sum(), len(base_c) - base_c.sum()]])
        except Exception:  # noqa: BLE001
            p_corr = np.nan
        rows.append({
            "condition": c, "panic_mean": cp.mean(), "panic_vs_base": cp.mean() - base_p.mean(),
            "cliffs_delta": delta, "p_panic_raw": p_panic,
            "correct_rate": cc.mean(), "correct_vs_base": cc.mean() - base_c.mean(),
            "p_correct_raw": p_corr,
        })
    contr = pd.DataFrame(rows)
    # Holm correction on panic p-values
    if not contr.empty:
        order = contr["p_panic_raw"].fillna(1).argsort().values
        m = len(order)
        adj = np.empty(m)
        prev = 0
        for rank, idx in enumerate(order):
            val = (m - rank) * contr["p_panic_raw"].fillna(1).iloc[idx]
            prev = max(prev, min(val, 1.0))
            adj[idx] = prev
        contr["p_panic_holm"] = adj
        print(contr.round(4).to_string(index=False))
        contr.to_csv(outdir / "contrasts.csv", index=False)

    # --- task-controlled correctness (the partial run left task mix unbalanced,
    #     and infeasible tasks are constant-0; both must be controlled for) ---
    print("\n=== Correctness controlled for task ===")
    task_rate = df.groupby("task_id")["correct"].mean()
    feasible = task_rate[(task_rate > 0.0) & (task_rate < 1.0)].index.tolist()
    dropped = [t for t in task_rate.index if t not in feasible]
    if dropped:
        print(f"(excluding non-discriminating tasks {dropped}: "
              f"rates {task_rate[dropped].round(2).to_dict()})")
    feas = df[df.task_id.isin(feasible)].copy()
    pt = feas.pivot_table(index="condition", columns="task_id", values="correct",
                          aggfunc="mean", observed=True)
    strat = pt.mean(axis=1).sort_values(ascending=False)
    print("Equal-task-weighted correctness per condition:")
    for c, v in strat.items():
        print(f"  {c:9s} {v:.3f}   per-task {pt.loc[c].round(2).to_dict()}")
    try:
        import statsmodels.formula.api as smf
        order = [BASELINE] + [c for c in CONDITION_ORDER if c != BASELINE]
        feas["cond"] = pd.Categorical(feas.condition.astype(str), order)
        feas["correct_i"] = feas.correct.astype(int)
        m = smf.logit("correct_i ~ C(cond) + C(task_id)", data=feas).fit(disp=0)
        print(f"\nLogit correct ~ condition + task (ref='{BASELINE}'):")
        ps = [(n, c, p) for n, c, p in zip(m.params.index, m.params.values, m.pvalues.values)
              if "C(cond)" in n]
        praw = np.array([p for _, _, p in ps])
        ordr = praw.argsort(); adj = np.empty(len(praw)); prev = 0
        for rank, idx in enumerate(ordr):
            prev = max(prev, min((len(praw) - rank) * praw[idx], 1.0)); adj[idx] = prev
        for (n, c, p), ph in zip(ps, adj):
            lab = n.split("T.")[-1].rstrip("]")
            print(f"  {lab:9s} OR={np.exp(c):5.2f}  p={p:.4f}  p_holm={ph:.4f}")
    except Exception as e:  # noqa: BLE001
        print("  (logit skipped:", e, ")")

    # --- trajectory: panic vs remaining budget proxy (calls_used among budgeted) ---
    print("\n=== Trajectory: 2nd-half SQL error rate by condition ===")
    traj = df[df.condition != "control"].groupby("condition", observed=True)["err_rate_2nd_half"].mean()
    print(traj.round(3).to_string())

    _plots(df, summ, outdir)
    print(f"\nplots + tables written to {outdir}/")
    _verdict(df)


def _plots(df, summ, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    conds = [c for c in CONDITION_ORDER if c in summ.index]
    x = np.arange(len(conds))
    fig, ax = plt.subplots(1, 2, figsize=(13, 5))

    cr = summ.loc[conds, "correct_rate"].values
    yerr = [cr - summ.loc[conds, "correct_lo"].values, summ.loc[conds, "correct_hi"].values - cr]
    ax[0].bar(x, cr, color="#4C72B0"); ax[0].errorbar(x, cr, yerr=yerr, fmt="none", ecolor="k", capsize=4)
    ax[0].set_xticks(x); ax[0].set_xticklabels(conds, rotation=30); ax[0].set_ylim(0, 1.05)
    ax[0].set_title("Correctness by framing"); ax[0].set_ylabel("P(correct)")

    pm = summ.loc[conds, "panic_mean"].values
    yerr = [pm - summ.loc[conds, "panic_lo"].values, summ.loc[conds, "panic_hi"].values - pm]
    ax[1].bar(x, pm, color="#C44E52"); ax[1].errorbar(x, pm, yerr=yerr, fmt="none", ecolor="k", capsize=4)
    ax[1].set_xticks(x); ax[1].set_xticklabels(conds, rotation=30)
    ax[1].set_title("Panic (judge, blinded) by framing"); ax[1].set_ylabel("panic score")
    fig.tight_layout(); fig.savefig(outdir / "by_condition.png", dpi=130); plt.close(fig)


def _verdict(df):
    print("\n=== Hypothesis read-out (descriptive) ===")
    m = df.groupby("condition", observed=True)[["panic", "correct", "calls_used"]].mean()
    def g(c, col):
        return m.loc[c, col] if c in m.index else float("nan")
    base = BASELINE
    print(f"baseline '{base}': panic={g(base,'panic'):.3f} correct={g(base,'correct'):.3f}")
    for c in ["money", "time", "dubloons", "latinum"]:
        if c in m.index:
            print(f"  {c:9s} panic {g(c,'panic'):.3f} ({g(c,'panic')-g(base,'panic'):+.3f}) | "
                  f"correct {g(c,'correct'):.3f} ({g(c,'correct')-g(base,'correct'):+.3f})")
    print("\nH1 money->careful/good : compare money correctness & panic vs baseline above")
    print("H2 time->worse/panicky : expect time panic up, correctness down")
    print("H3 whimsy->better/calm : expect dubloons/latinum panic down, correctness up")


if __name__ == "__main__":
    main()
