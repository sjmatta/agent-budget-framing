"""Re-score panic on already-recorded agent traces with the CURRENT blinding.

Agent behavior is unchanged; only the judge's (blinded) view of the trace changes.
Use this to test whether a panic difference was a judge-blinding artifact without
paying to re-run agents. Writes <in>.rejudged.jsonl with refreshed panic_score.

Usage: uv run python rejudge.py --in runs/exp3_time.jsonl
"""

from __future__ import annotations

import argparse
import json

from conditions import CONDITIONS
import judge as judgemod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--model", default=judgemod.JUDGE_MODEL_DEFAULT)
    args = ap.parse_args()

    rows = []
    for line in open(args.inp):
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    rows = [r for r in rows if r.get("status") != "error"]
    print(f"re-judging {len(rows)} traces with current blinding...")

    metric, jm = judgemod.make_panic_metric(args.model)
    out = args.inp.replace(".jsonl", ".rejudged.jsonl")
    try:
        with open(out, "w") as fh:
            for i, r in enumerate(rows):
                cond = CONDITIONS[r["condition"]]
                old = r.get("panic_score")
                panic, reason = judgemod.score_panic(r, cond, metric)
                r["panic_score"] = panic
                r["panic_reason"] = reason
                fh.write(json.dumps(r) + "\n")
                if (i + 1) % 10 == 0:
                    print(f"  {i+1}/{len(rows)}  (last: {r['condition']} {old:.2f}->{panic:.2f})")
    finally:
        jm.client.close()
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
